"""Short business transactions used by durable workflow nodes."""

from __future__ import annotations

from time import perf_counter
from typing import cast
from uuid import UUID

from pydantic import JsonValue

from app.db.repositories import GenerationRunRepository, ProjectRepository
from app.db.session import Database
from app.domain.enums import RunStatus
from app.domain.exceptions import (
    DuplicateWorkflowThreadError,
    EntityNotFoundError,
)
from app.domain.schemas import (
    GenerationRunComplete,
    GenerationRunCreate,
    GenerationRunFail,
    GenerationRunProgress,
    GenerationRunRead,
)
from app.recommendation.service import RecommendationService
from app.workflow.exceptions import WorkflowStateError
from app.workflow.schemas import WorkflowPhase
from app.workflow.state import RecommendationWorkflowState


class WorkflowRunPersistence:
    """Map technical workflow state to one source-of-truth GenerationRun."""

    def __init__(
        self,
        database: Database,
        recommendation_service: RecommendationService,
    ) -> None:
        self._database = database
        self._recommendation_service = recommendation_service

    async def initialize(self, state: RecommendationWorkflowState) -> UUID:
        """Create one idempotent run under a transaction-scoped advisory lock."""
        thread_id = state["thread_id"]
        workflow_id = state["workflow_id"]
        request = state["request"]
        project_id = UUID(cast(str, request["project_id"]))
        async with self._database.transaction() as session:
            projects = ProjectRepository(session)
            if await projects.get_by_id(project_id) is None:
                raise EntityNotFoundError("Project", project_id)
            runs = GenerationRunRepository(session)
            await runs.acquire_workflow_thread_lock(thread_id)
            existing = await runs.get_by_workflow_thread_id(thread_id)
            if existing is not None:
                existing_workflow_id = existing.provider_parameters.get("workflow_id")
                if existing_workflow_id == workflow_id:
                    return existing.id
                raise DuplicateWorkflowThreadError(thread_id)

            run = await runs.create(
                GenerationRunCreate.model_validate(
                    {
                        "project_id": project_id,
                        "brief_text": request["brief"],
                        "prompt_recommendation": {},
                        "provider": self._recommendation_service.provider_name,
                        "model": self._recommendation_service.model_name,
                        "generation_method": request.get("generation_method") or "unspecified",
                        "provider_parameters": {
                            "workflow_id": workflow_id,
                            "thread_id": thread_id,
                            "workflow_phase": WorkflowPhase.INITIALIZING.value,
                            "revision_count": 0,
                            "query_type": request["query_type"],
                            "target_platform": request.get("target_platform"),
                            "generation_method": request.get("generation_method"),
                            "embedding_provider": (
                                self._recommendation_service.embedding_provider_name
                            ),
                            "embedding_model": self._recommendation_service.embedding_model_name,
                        },
                        "status": RunStatus.RUNNING,
                        "trace_id": request.get("trace_id"),
                        "workflow_thread_id": thread_id,
                    }
                )
            )
            return run.id

    async def mark_waiting(
        self,
        state: RecommendationWorkflowState,
        *,
        latency_ms: int,
    ) -> None:
        """Persist review-safe data before the graph reaches `interrupt()`."""
        run_id = _required_run_id(state)
        async with self._database.transaction() as session:
            await GenerationRunRepository(session).mark_waiting_for_human(
                run_id,
                GenerationRunProgress(
                    prompt_recommendation=self._recommendation_payload(state),
                    provider_parameters=self._provider_parameters(state),
                    latency_ms=latency_ms,
                ),
            )

    async def claim_resume(self, run_id: UUID) -> None:
        """Claim exactly one human command with a row-level lock."""
        async with self._database.transaction() as session:
            await GenerationRunRepository(session).claim_human_resume(run_id)

    async def reconcile_unaccepted_resume(
        self,
        state: RecommendationWorkflowState,
        *,
        checkpoint_id: str,
    ) -> None:
        """Safely release a claim only while the checkpoint is still unchanged."""
        run_id = _required_run_id(state)
        async with self._database.transaction() as session:
            await GenerationRunRepository(session).reconcile_unaccepted_human_resume(
                run_id,
                thread_id=state["thread_id"],
                checkpoint_id=checkpoint_id,
            )

    async def complete(
        self,
        state: RecommendationWorkflowState,
        *,
        outcome: str,
        latency_ms: int,
    ) -> None:
        """Persist one approved or rejected terminal business outcome."""
        run_id = _required_run_id(state)
        parameters = self._provider_parameters(state)
        parameters["workflow_outcome"] = outcome
        async with self._database.transaction() as session:
            await GenerationRunRepository(session).mark_completed(
                run_id,
                GenerationRunComplete(
                    prompt_recommendation=self._recommendation_payload(state),
                    provider_parameters=parameters,
                    latency_ms=latency_ms,
                ),
            )

    async def fail(
        self,
        state: RecommendationWorkflowState,
        *,
        error_code: str,
        latency_ms: int,
    ) -> None:
        """Persist a stable technical failure without internal exception data."""
        run_id_text = state.get("run_id")
        if run_id_text is None:
            return
        async with self._database.transaction() as session:
            await GenerationRunRepository(session).mark_failed(
                UUID(run_id_text),
                GenerationRunFail(
                    error_code=error_code,
                    latency_ms=latency_ms,
                    prompt_recommendation=self._recommendation_payload(state),
                    provider_parameters=self._provider_parameters(state),
                ),
            )

    async def read(self, run_id: UUID) -> GenerationRunRead:
        """Return a detached validated snapshot of one business run."""
        async with self._database.transaction() as session:
            run = await GenerationRunRepository(session).get_by_id(run_id)
            if run is None:
                raise EntityNotFoundError("GenerationRun", run_id)
            return GenerationRunRead.model_validate(run)

    @staticmethod
    def _recommendation_payload(
        state: RecommendationWorkflowState,
    ) -> dict[str, JsonValue]:
        return state["recommendation"] or {}

    @staticmethod
    def _provider_parameters(
        state: RecommendationWorkflowState,
    ) -> dict[str, JsonValue]:
        request = state["request"]
        parameters: dict[str, object] = {
            "workflow_id": state["workflow_id"],
            "thread_id": state["thread_id"],
            "workflow_phase": state["phase"],
            "revision_count": state.get("revision_count", 0),
            "human_decision": state.get("human_decision"),
            "human_feedback": state.get("human_feedback"),
            "positive_evidence": state.get("positive_evidence", []),
            "failure_evidence": state.get("failure_evidence", []),
            "critique": state.get("critique", {}),
            "query_type": request.get("query_type"),
            "target_platform": request.get("target_platform"),
            "generation_method": request.get("generation_method"),
        }
        return cast(dict[str, JsonValue], parameters)


def elapsed_ms(started: float) -> int:
    """Return a non-negative elapsed wall-clock measurement."""
    return max(0, round((perf_counter() - started) * 1_000))


def _required_run_id(state: RecommendationWorkflowState) -> UUID:
    value = state["run_id"]
    if value is None:
        raise WorkflowStateError("Workflow persistence requires a GenerationRun ID.")
    return UUID(value)
