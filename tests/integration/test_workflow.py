"""Durable workflow integration tests against real PostgreSQL checkpoints."""

from __future__ import annotations

import asyncio
import json
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
    WorkflowRevisionLimitError,
)
from app.workflow.persistence import WorkflowRunPersistence
from app.workflow.schemas import HumanDecision, WorkflowPhase, WorkflowResumeCommand
from app.workflow.service import RecommendationWorkflowService
from app.workflow.state import RecommendationWorkflowState
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


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
        await checkpointer.adelete_thread(thread_id)

    assert rejected.phase is WorkflowPhase.REJECTED
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
    assert final.phase in {WorkflowPhase.COMPLETED, WorkflowPhase.REJECTED}
    assert final.run_status is RunStatus.COMPLETED


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
