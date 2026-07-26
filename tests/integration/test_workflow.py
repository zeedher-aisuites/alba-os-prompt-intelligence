"""Durable workflow integration tests against real PostgreSQL checkpoints."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from app.core.config import Settings
from app.db.repositories import GenerationRunRepository, ProjectRepository
from app.db.session import Database
from app.domain.enums import QueryType, RunStatus
from app.domain.exceptions import InvalidRunTransitionError
from app.domain.schemas import ProjectCreate
from app.embeddings.providers import FakeEmbeddingProvider
from app.recommendation.exceptions import RecommendationProviderUnavailableError
from app.recommendation.protocol import RecommendationDraftValidator
from app.recommendation.providers import FakeRecommendationProvider
from app.recommendation.schemas import (
    RecommendationContext,
    RecommendationDraft,
    RecommendationRequest,
)
from app.recommendation.service import RecommendationService
from app.workflow.checkpoint import (
    open_workflow_checkpointer,
    setup_workflow_checkpointer,
)
from app.workflow.exceptions import (
    WorkflowAlreadyExistsError,
    WorkflowNotFoundError,
    WorkflowNotWaitingError,
    WorkflowResumeNotAcceptedError,
    WorkflowResumeReconciliationRejectedError,
    WorkflowResumeReconciliationRequiredError,
    WorkflowRevisionLimitError,
)
from app.workflow.persistence import WorkflowRunPersistence
from app.workflow.schemas import HumanDecision, WorkflowPhase, WorkflowResumeCommand
from app.workflow.service import RecommendationWorkflowService
from app.workflow.state import RecommendationWorkflowState
from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class FailingRecommendationProvider:
    """Typed provider failure used to test durable failure auditing."""

    @property
    def provider_name(self) -> str:
        return "failing-test"

    @property
    def model_name(self) -> str:
        return "failing-v1"

    @property
    def repair_attempts_used(self) -> int:
        return 0

    async def generate_recommendation(
        self,
        context: RecommendationContext,
        *,
        validate: RecommendationDraftValidator | None = None,
    ) -> RecommendationDraft:
        raise RecommendationProviderUnavailableError("Provider unavailable in test.")


class FailingFinalPersistence(WorkflowRunPersistence):
    """Fail only the terminal write to exercise resume failure recovery."""

    async def complete(
        self,
        state: RecommendationWorkflowState,
        *,
        outcome: str,
        latency_ms: int,
    ) -> None:
        del state, outcome, latency_ms
        raise RuntimeError("Synthetic final persistence failure.")


class FailingResumeInvocationService(RecommendationWorkflowService):
    """Inject a bounded failure at the graph-invocation boundary."""

    def __init__(
        self,
        checkpointer: AsyncPostgresSaver,
        recommendation_service: RecommendationService,
        persistence: WorkflowRunPersistence,
        failure_stage: str,
        failure_message: str,
    ) -> None:
        super().__init__(checkpointer, recommendation_service, persistence)
        self._failure_stage = failure_stage
        self._failure_message = failure_message

    async def _invoke_resume_graph(
        self,
        command: WorkflowResumeCommand,
        config: RunnableConfig,
    ) -> None:
        if self._failure_stage == "before_command":
            raise RuntimeError(self._failure_message)
        await self._simulate_graph_ainvoke(
            Command(resume=command.model_dump(mode="json")),
            config,
        )

    async def _simulate_graph_ainvoke(
        self,
        command: object,
        config: RunnableConfig,
    ) -> None:
        """Fail after building Command at the same boundary as graph.ainvoke."""
        del command, config
        raise RuntimeError(self._failure_message)


async def project_and_request(database: Database) -> RecommendationRequest:
    slug = f"workflow-{uuid4().hex[:12]}"
    async with database.transaction() as session:
        project = await ProjectRepository(session).create(
            ProjectCreate(name="Workflow Integration", slug=slug)
        )
    return RecommendationRequest(
        project_id=project.id,
        brief="Create a safe editorial portrait.",
        query_type=QueryType.AI_INFLUENCER,
        constraints=["Keep the face"],
        trace_id="workflow-test",
    )


def workflow_service(
    database: Database,
    checkpointer: AsyncPostgresSaver,
    *,
    failing: bool = False,
) -> RecommendationWorkflowService:
    provider = FailingRecommendationProvider() if failing else FakeRecommendationProvider()
    recommendation = RecommendationService(
        database,
        FakeEmbeddingProvider(),
        provider,
    )
    persistence = WorkflowRunPersistence(database, recommendation)
    return RecommendationWorkflowService(
        checkpointer,
        recommendation,
        persistence,
    )


async def stored_run(database: Database, run_id: UUID):
    async with database.transaction() as session:
        return await GenerationRunRepository(session).get_by_id(run_id)


async def assert_workflow_consistency(
    database: Database,
    service: RecommendationWorkflowService,
    thread_id: str,
    *,
    phase: WorkflowPhase,
    waiting_for_human: bool,
    run_status: RunStatus,
    human_decision: HumanDecision | None,
    revision_count: int,
    workflow_outcome: str | None,
) -> None:
    """Assert one externally visible checkpoint/business-run invariant."""
    result = await service.status(thread_id)

    assert result.phase is phase
    assert result.waiting_for_human is waiting_for_human
    assert result.run_status is run_status
    assert result.human_decision is human_decision
    assert result.revision_count == revision_count
    if waiting_for_human:
        assert result.interrupt is not None
    else:
        assert result.interrupt is None
    assert result.run_id is not None
    run = await stored_run(database, result.run_id)
    assert run is not None
    assert run.provider_parameters.get("workflow_outcome") == workflow_outcome


async def run_cli_resume(
    test_settings: Settings,
    thread_id: str,
    *,
    decision: HumanDecision,
) -> tuple[int, dict[str, object], str]:
    """Run the real Windows-compatible CLI in a separate process."""
    environment = os.environ.copy()
    environment["ALBA_DATABASE_URL"] = (
        test_settings.test_database_url.get_secret_value().unicode_string()
    )
    environment["ALBA_ENVIRONMENT"] = "test"
    completed = await asyncio.to_thread(
        subprocess.run,
        [
            sys.executable,
            "-m",
            "scripts.recommendation_workflow",
            "resume",
            "--thread-id",
            thread_id,
            "--decision",
            decision.value,
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    payload = cast(dict[str, object], json.loads(completed.stdout) if completed.stdout else {})
    return completed.returncode, payload, completed.stderr


@pytest.mark.postgres
async def test_checkpoint_survives_new_runtime_and_approve(
    database: Database,
    test_settings: Settings,
) -> None:
    request = await project_and_request(database)
    thread_id = f"test-approve-{uuid4().hex}"
    try:
        async with open_workflow_checkpointer(
            test_settings,
            database_url=test_settings.test_database_url.get_secret_value(),
        ) as first_checkpointer:
            await setup_workflow_checkpointer(first_checkpointer, database)
            started = await workflow_service(database, first_checkpointer).start(
                request,
                thread_id=thread_id,
            )

        assert started.phase is WorkflowPhase.WAITING_FOR_HUMAN
        assert started.run_status is RunStatus.WAITING_FOR_HUMAN
        assert started.interrupt is not None
        first_checkpoint_id = started.checkpoint_id

        async with open_workflow_checkpointer(
            test_settings,
            database_url=test_settings.test_database_url.get_secret_value(),
        ) as second_checkpointer:
            restarted_service = workflow_service(database, second_checkpointer)
            inspected = await restarted_service.status(thread_id)
            completed = await restarted_service.resume(
                thread_id,
                WorkflowResumeCommand(decision=HumanDecision.APPROVE),
            )
            await assert_workflow_consistency(
                database,
                restarted_service,
                thread_id,
                phase=WorkflowPhase.COMPLETED,
                waiting_for_human=False,
                run_status=RunStatus.COMPLETED,
                human_decision=HumanDecision.APPROVE,
                revision_count=0,
                workflow_outcome="approve",
            )

        assert inspected.checkpoint_id == first_checkpoint_id
        assert completed.phase is WorkflowPhase.COMPLETED
        assert completed.run_status is RunStatus.COMPLETED
        assert completed.run_id is not None
        run = await stored_run(database, completed.run_id)
        assert run is not None
        assert run.provider_parameters["workflow_outcome"] == "approve"
        assert run.workflow_thread_id == thread_id
        async with open_workflow_checkpointer(
            test_settings,
            database_url=test_settings.test_database_url.get_secret_value(),
        ) as terminal_checkpointer:
            with pytest.raises(WorkflowNotWaitingError):
                await workflow_service(database, terminal_checkpointer).resume(
                    thread_id,
                    WorkflowResumeCommand(decision=HumanDecision.REJECT),
                )
    finally:
        async with open_workflow_checkpointer(
            test_settings,
            database_url=test_settings.test_database_url.get_secret_value(),
        ) as checkpointer:
            await checkpointer.adelete_thread(thread_id)


@pytest.mark.postgres
async def test_single_revision_preserves_feedback_then_rejects(
    database: Database,
    test_settings: Settings,
) -> None:
    request = await project_and_request(database)
    thread_id = f"test-revise-{uuid4().hex}"
    feedback = "Increase negative space and retain the editorial crop."
    async with open_workflow_checkpointer(
        test_settings,
        database_url=test_settings.test_database_url.get_secret_value(),
    ) as checkpointer:
        await setup_workflow_checkpointer(checkpointer, database)
        service = workflow_service(database, checkpointer)
        await service.start(request, thread_id=thread_id)
        before_revision = await service.status(thread_id)
        revised = await service.resume(
            thread_id,
            WorkflowResumeCommand(
                decision=HumanDecision.REVISE,
                feedback=feedback,
            ),
        )

        assert revised.phase is WorkflowPhase.WAITING_FOR_HUMAN
        assert revised.revision_count == 1
        assert revised.recommendation is not None
        assert feedback in revised.recommendation.recommended_prompt
        assert before_revision.interrupt is not None
        assert revised.interrupt is not None
        assert revised.interrupt.positive_evidence == before_revision.interrupt.positive_evidence
        assert revised.interrupt.failure_evidence == before_revision.interrupt.failure_evidence
        await assert_workflow_consistency(
            database,
            service,
            thread_id,
            phase=WorkflowPhase.WAITING_FOR_HUMAN,
            waiting_for_human=True,
            run_status=RunStatus.WAITING_FOR_HUMAN,
            human_decision=HumanDecision.REVISE,
            revision_count=1,
            workflow_outcome=None,
        )

        with pytest.raises(WorkflowRevisionLimitError):
            await service.resume(
                thread_id,
                WorkflowResumeCommand(
                    decision=HumanDecision.REVISE,
                    feedback="Try a second revision.",
                ),
            )

        rejected = await service.resume(
            thread_id,
            WorkflowResumeCommand(decision=HumanDecision.REJECT),
        )
        await assert_workflow_consistency(
            database,
            service,
            thread_id,
            phase=WorkflowPhase.COMPLETED,
            waiting_for_human=False,
            run_status=RunStatus.COMPLETED,
            human_decision=HumanDecision.REJECT,
            revision_count=1,
            workflow_outcome="reject",
        )
        await checkpointer.adelete_thread(thread_id)

    assert rejected.phase is WorkflowPhase.COMPLETED
    assert rejected.run_status is RunStatus.COMPLETED
    assert rejected.human_feedback == feedback
    assert rejected.run_id is not None
    run = await stored_run(database, rejected.run_id)
    assert run is not None
    assert run.provider_parameters["workflow_outcome"] == "reject"
    assert run.provider_parameters["human_feedback"] == feedback


@pytest.mark.postgres
async def test_concurrent_resume_allows_one_terminal_decision(
    database: Database,
    test_settings: Settings,
) -> None:
    request = await project_and_request(database)
    thread_id = f"test-concurrent-{uuid4().hex}"
    async with open_workflow_checkpointer(
        test_settings,
        database_url=test_settings.test_database_url.get_secret_value(),
    ) as checkpointer:
        await setup_workflow_checkpointer(checkpointer, database)
        service = workflow_service(database, checkpointer)
        await service.start(request, thread_id=thread_id)

        outcomes = await asyncio.gather(
            service.resume(
                thread_id,
                WorkflowResumeCommand(decision=HumanDecision.APPROVE),
            ),
            service.resume(
                thread_id,
                WorkflowResumeCommand(decision=HumanDecision.REJECT),
            ),
            return_exceptions=True,
        )
        final = await service.status(thread_id)
        await checkpointer.adelete_thread(thread_id)

    assert sum(isinstance(item, InvalidRunTransitionError) for item in outcomes) == 1
    assert sum(not isinstance(item, BaseException) for item in outcomes) == 1
    assert final.phase is WorkflowPhase.COMPLETED
    assert final.run_status is RunStatus.COMPLETED
    assert final.human_decision in {HumanDecision.APPROVE, HumanDecision.REJECT}
    decision = final.human_decision
    assert decision is not None
    assert final.run_id is not None
    run = await stored_run(database, final.run_id)
    assert run is not None
    assert run.provider_parameters["workflow_outcome"] == decision.value


@pytest.mark.postgres
async def test_cli_approve_from_another_process_normalizes_outer_thread_spaces(
    database: Database,
    test_settings: Settings,
) -> None:
    """The real CLI resumes a fake workflow without an Ollama dependency."""
    request = await project_and_request(database)
    thread_id = f"test-cli-approve-{uuid4().hex}"
    async with open_workflow_checkpointer(
        test_settings,
        database_url=test_settings.test_database_url.get_secret_value(),
    ) as checkpointer:
        await setup_workflow_checkpointer(checkpointer, database)
        service = workflow_service(database, checkpointer)
        await service.start(request, thread_id=thread_id)

        exit_code, payload, stderr = await run_cli_resume(
            test_settings,
            f"  {thread_id}  ",
            decision=HumanDecision.APPROVE,
        )

        assert exit_code == 0, stderr
        assert payload["thread_id"] == thread_id
        assert payload["phase"] == WorkflowPhase.COMPLETED.value
        assert payload["run_status"] == RunStatus.COMPLETED.value
        await assert_workflow_consistency(
            database,
            service,
            thread_id,
            phase=WorkflowPhase.COMPLETED,
            waiting_for_human=False,
            run_status=RunStatus.COMPLETED,
            human_decision=HumanDecision.APPROVE,
            revision_count=0,
            workflow_outcome="approve",
        )
        await checkpointer.adelete_thread(thread_id)


@pytest.mark.postgres
async def test_legacy_unaccepted_claim_can_be_reconciled_then_retried(
    database: Database,
    test_settings: Settings,
) -> None:
    """Recover only the exact paused-checkpoint/running-run state from the incident."""
    request = await project_and_request(database)
    thread_id = f"test-reconcile-{uuid4().hex}"
    async with open_workflow_checkpointer(
        test_settings,
        database_url=test_settings.test_database_url.get_secret_value(),
    ) as checkpointer:
        await setup_workflow_checkpointer(checkpointer, database)
        service = workflow_service(database, checkpointer)
        started = await service.start(request, thread_id=thread_id)
        assert started.run_id is not None
        async with database.transaction() as session:
            await GenerationRunRepository(session).claim_human_resume(started.run_id)

        with pytest.raises(WorkflowResumeReconciliationRequiredError):
            await service.resume(
                thread_id,
                WorkflowResumeCommand(decision=HumanDecision.APPROVE),
            )

        reconciled = await service.reconcile_unaccepted_resume(thread_id)
        assert reconciled.run_id == started.run_id
        await assert_workflow_consistency(
            database,
            service,
            thread_id,
            phase=WorkflowPhase.WAITING_FOR_HUMAN,
            waiting_for_human=True,
            run_status=RunStatus.WAITING_FOR_HUMAN,
            human_decision=None,
            revision_count=0,
            workflow_outcome=None,
        )
        assert reconciled.run_id is not None
        reconciled_run = await stored_run(database, reconciled.run_id)
        assert reconciled_run is not None
        history = reconciled_run.provider_parameters["resume_reconciliations"]
        assert isinstance(history, list)
        assert history[-1]["code"] == "WORKFLOW_RESUME_NOT_ACCEPTED"

        await service.resume(
            thread_id,
            WorkflowResumeCommand(decision=HumanDecision.APPROVE),
        )
        await assert_workflow_consistency(
            database,
            service,
            thread_id,
            phase=WorkflowPhase.COMPLETED,
            waiting_for_human=False,
            run_status=RunStatus.COMPLETED,
            human_decision=HumanDecision.APPROVE,
            revision_count=0,
            workflow_outcome="approve",
        )
        await checkpointer.adelete_thread(thread_id)


@pytest.mark.postgres
async def test_reconciliation_rejects_a_consistent_paused_workflow(
    database: Database,
    test_settings: Settings,
) -> None:
    """A normal waiting run is never rewritten merely because reconcile was requested."""
    request = await project_and_request(database)
    thread_id = f"test-reconcile-reject-{uuid4().hex}"
    async with open_workflow_checkpointer(
        test_settings,
        database_url=test_settings.test_database_url.get_secret_value(),
    ) as checkpointer:
        await setup_workflow_checkpointer(checkpointer, database)
        service = workflow_service(database, checkpointer)
        await service.start(request, thread_id=thread_id)

        with pytest.raises(WorkflowResumeReconciliationRejectedError):
            await service.reconcile_unaccepted_resume(thread_id)

        await assert_workflow_consistency(
            database,
            service,
            thread_id,
            phase=WorkflowPhase.WAITING_FOR_HUMAN,
            waiting_for_human=True,
            run_status=RunStatus.WAITING_FOR_HUMAN,
            human_decision=None,
            revision_count=0,
            workflow_outcome=None,
        )
        await checkpointer.adelete_thread(thread_id)


@pytest.mark.postgres
@pytest.mark.parametrize("failure_stage", ["before_command", "during_ainvoke"])
async def test_unaccepted_resume_is_reconciled_and_can_be_retried(
    database: Database,
    test_settings: Settings,
    failure_stage: str,
) -> None:
    """A failure before checkpoint advancement cannot leave a claimed run behind."""
    request = await project_and_request(database)
    thread_id = f"test-retry-{failure_stage}-{uuid4().hex}"
    async with open_workflow_checkpointer(
        test_settings,
        database_url=test_settings.test_database_url.get_secret_value(),
    ) as checkpointer:
        await setup_workflow_checkpointer(checkpointer, database)
        recommendation = RecommendationService(
            database,
            FakeEmbeddingProvider(),
            FakeRecommendationProvider(),
        )
        service = FailingResumeInvocationService(
            checkpointer,
            recommendation,
            WorkflowRunPersistence(database, recommendation),
            failure_stage=failure_stage,
            failure_message=(
                "Synthetic failure before Command construction."
                if failure_stage == "before_command"
                else "Synthetic failure during graph invocation."
            ),
        )
        await service.start(request, thread_id=thread_id)

        with pytest.raises(WorkflowResumeNotAcceptedError) as error:
            await service.resume(
                thread_id,
                WorkflowResumeCommand(decision=HumanDecision.APPROVE),
            )
        assert isinstance(error.value.__cause__, RuntimeError)

        await assert_workflow_consistency(
            database,
            service,
            thread_id,
            phase=WorkflowPhase.WAITING_FOR_HUMAN,
            waiting_for_human=True,
            run_status=RunStatus.WAITING_FOR_HUMAN,
            human_decision=None,
            revision_count=0,
            workflow_outcome=None,
        )
        retry_service = workflow_service(database, checkpointer)
        await retry_service.resume(
            thread_id,
            WorkflowResumeCommand(decision=HumanDecision.APPROVE),
        )
        await assert_workflow_consistency(
            database,
            retry_service,
            thread_id,
            phase=WorkflowPhase.COMPLETED,
            waiting_for_human=False,
            run_status=RunStatus.COMPLETED,
            human_decision=HumanDecision.APPROVE,
            revision_count=0,
            workflow_outcome="approve",
        )
        await checkpointer.adelete_thread(thread_id)


@pytest.mark.postgres
async def test_concurrent_approves_allow_one_terminal_decision(
    database: Database,
    test_settings: Settings,
) -> None:
    """Two approve requests contend on the row lock and produce one completion."""
    request = await project_and_request(database)
    thread_id = f"test-concurrent-approve-{uuid4().hex}"
    async with open_workflow_checkpointer(
        test_settings,
        database_url=test_settings.test_database_url.get_secret_value(),
    ) as checkpointer:
        await setup_workflow_checkpointer(checkpointer, database)
        service = workflow_service(database, checkpointer)
        await service.start(request, thread_id=thread_id)

        outcomes = await asyncio.gather(
            service.resume(
                thread_id,
                WorkflowResumeCommand(decision=HumanDecision.APPROVE),
            ),
            service.resume(
                thread_id,
                WorkflowResumeCommand(decision=HumanDecision.APPROVE),
            ),
            return_exceptions=True,
        )

        assert sum(isinstance(item, InvalidRunTransitionError) for item in outcomes) == 1
        assert sum(not isinstance(item, BaseException) for item in outcomes) == 1
        await assert_workflow_consistency(
            database,
            service,
            thread_id,
            phase=WorkflowPhase.COMPLETED,
            waiting_for_human=False,
            run_status=RunStatus.COMPLETED,
            human_decision=HumanDecision.APPROVE,
            revision_count=0,
            workflow_outcome="approve",
        )
        await checkpointer.adelete_thread(thread_id)


@pytest.mark.postgres
async def test_provider_failure_marks_run_and_checkpoint_failed(
    database: Database,
    test_settings: Settings,
) -> None:
    request = await project_and_request(database)
    thread_id = f"test-failure-{uuid4().hex}"
    async with open_workflow_checkpointer(
        test_settings,
        database_url=test_settings.test_database_url.get_secret_value(),
    ) as checkpointer:
        await setup_workflow_checkpointer(checkpointer, database)
        service = workflow_service(database, checkpointer, failing=True)

        with pytest.raises(RecommendationProviderUnavailableError):
            await service.start(request, thread_id=thread_id)

        failed = await service.status(thread_id)
        await checkpointer.adelete_thread(thread_id)

    assert failed.phase is WorkflowPhase.FAILED
    assert failed.run_status is RunStatus.FAILED
    assert failed.error_code == "RECOMMENDATION_PROVIDER_UNAVAILABLE"
    assert failed.run_id is not None
    run = await stored_run(database, failed.run_id)
    assert run is not None
    assert run.error_code == "RECOMMENDATION_PROVIDER_UNAVAILABLE"
    serialized = json.dumps(
        {
            "recommendation": run.prompt_recommendation,
            "parameters": run.provider_parameters,
        }
    )
    assert "embedding" not in serialized
    assert "vector" not in serialized
    assert "Traceback" not in serialized


@pytest.mark.postgres
async def test_duplicate_start_is_rejected_without_second_run(
    database: Database,
    test_settings: Settings,
) -> None:
    request = await project_and_request(database)
    thread_id = f"test-duplicate-{uuid4().hex}"
    async with open_workflow_checkpointer(
        test_settings,
        database_url=test_settings.test_database_url.get_secret_value(),
    ) as checkpointer:
        await setup_workflow_checkpointer(checkpointer, database)
        service = workflow_service(database, checkpointer)
        started = await service.start(request, thread_id=thread_id)
        with pytest.raises(WorkflowAlreadyExistsError):
            await service.start(request, thread_id=thread_id)
        await checkpointer.adelete_thread(thread_id)

    assert started.run_id is not None
    async with database.transaction() as session:
        runs = await GenerationRunRepository(session).list_by_project(request.project_id)
    assert [run.id for run in runs] == [started.run_id]


@pytest.mark.postgres
async def test_final_persistence_failure_marks_workflow_failed(
    database: Database,
    test_settings: Settings,
) -> None:
    request = await project_and_request(database)
    thread_id = f"test-final-failure-{uuid4().hex}"
    recommendation = RecommendationService(
        database,
        FakeEmbeddingProvider(),
        FakeRecommendationProvider(),
    )
    persistence = FailingFinalPersistence(database, recommendation)
    async with open_workflow_checkpointer(
        test_settings,
        database_url=test_settings.test_database_url.get_secret_value(),
    ) as checkpointer:
        await setup_workflow_checkpointer(checkpointer, database)
        service = RecommendationWorkflowService(
            checkpointer,
            recommendation,
            persistence,
        )
        await service.start(request, thread_id=thread_id)
        with pytest.raises(RuntimeError, match="Synthetic final persistence failure"):
            await service.resume(
                thread_id,
                WorkflowResumeCommand(decision=HumanDecision.APPROVE),
            )
        failed = await service.status(thread_id)
        await checkpointer.adelete_thread(thread_id)

    assert failed.phase is WorkflowPhase.FAILED
    assert failed.run_status is RunStatus.FAILED
    assert failed.error_code == "WORKFLOW_EXECUTION_FAILED"


@pytest.mark.postgres
async def test_missing_checkpoint_is_typed(
    database: Database,
    test_settings: Settings,
) -> None:
    async with open_workflow_checkpointer(
        test_settings,
        database_url=test_settings.test_database_url.get_secret_value(),
    ) as checkpointer:
        await setup_workflow_checkpointer(checkpointer, database)
        with pytest.raises(WorkflowNotFoundError):
            await workflow_service(database, checkpointer).status(f"missing-{uuid4().hex}")
