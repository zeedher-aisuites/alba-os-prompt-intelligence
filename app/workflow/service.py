"""Start, inspect, and resume durable recommendation workflows."""

# pyright: reportUnknownMemberType=false

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command, StateSnapshot
from psycopg import Error as PsycopgError
from pydantic import JsonValue, TypeAdapter

from app.core.exceptions import AlbaError
from app.domain.enums import RunStatus
from app.recommendation.exceptions import RecommendationError
from app.recommendation.schemas import PromptRecommendation, RecommendationRequest
from app.recommendation.service import RecommendationService
from app.workflow.checkpoint import checkpoint_config
from app.workflow.exceptions import (
    WorkflowAlreadyExistsError,
    WorkflowCheckpointUnavailableError,
    WorkflowNotFoundError,
    WorkflowNotWaitingError,
    WorkflowRevisionLimitError,
    WorkflowStateError,
)
from app.workflow.graph import (
    RecommendationWorkflowNodes,
    build_interrupt_payload,
    compile_recommendation_workflow,
)
from app.workflow.persistence import WorkflowRunPersistence
from app.workflow.schemas import (
    HumanDecision,
    RecommendationCritique,
    ThreadId,
    WorkflowPhase,
    WorkflowResult,
    WorkflowResumeCommand,
    WorkflowStart,
)
from app.workflow.state import RecommendationWorkflowState


class RecommendationWorkflowService:
    """Public durable workflow use cases around one compiled StateGraph."""

    def __init__(
        self,
        checkpointer: AsyncPostgresSaver,
        recommendation_service: RecommendationService,
        persistence: WorkflowRunPersistence,
        *,
        maximum_revisions: int = 1,
    ) -> None:
        if maximum_revisions != 1:
            raise ValueError("Stage 4 supports exactly one human-requested revision.")
        self._checkpointer = checkpointer
        self._persistence = persistence
        self._maximum_revisions = maximum_revisions
        self._graph = compile_recommendation_workflow(
            RecommendationWorkflowNodes(
                recommendation_service,
                persistence,
            ),
            checkpointer,
        )

    async def start(
        self,
        request: RecommendationRequest,
        *,
        thread_id: str | None = None,
        workflow_id: str | None = None,
    ) -> WorkflowResult:
        """Start a new durable workflow and return its first interrupt."""
        start = WorkflowStart(
            workflow_id=workflow_id or uuid4().hex,
            thread_id=thread_id or uuid4().hex,
            request=request,
        )
        config = checkpoint_config(start.thread_id)
        try:
            if await self._checkpointer.aget_tuple(config) is not None:
                raise WorkflowAlreadyExistsError(start.thread_id)
            now = datetime.now(UTC).isoformat()
            initial: RecommendationWorkflowState = {
                "workflow_id": start.workflow_id,
                "thread_id": start.thread_id,
                "project_id": str(request.project_id),
                "run_id": None,
                "request": cast(
                    dict[str, JsonValue],
                    request.model_dump(mode="json"),
                ),
                "phase": WorkflowPhase.INITIALIZING.value,
                "recommendation_context": None,
                "positive_evidence": [],
                "failure_evidence": [],
                "recommendation": None,
                "critique": None,
                "revision_count": 0,
                "human_decision": None,
                "human_feedback": None,
                "error_code": None,
                "started_at": now,
                "updated_at": now,
            }
            await self._graph.ainvoke(
                initial,
                config=config,
                durability="sync",
            )
            return await self.status(start.thread_id)
        except WorkflowAlreadyExistsError:
            raise
        except PsycopgError as exc:
            raise WorkflowCheckpointUnavailableError from exc
        except Exception as exc:
            await self._fail_from_checkpoint(start.thread_id, exc)
            raise

    async def status(self, thread_id: str) -> WorkflowResult:
        """Inspect the latest durable checkpoint and detached business run."""
        thread_id = cast(str, TypeAdapter(ThreadId).validate_python(thread_id))
        config = checkpoint_config(thread_id)
        try:
            snapshot = await self._graph.aget_state(config)
        except PsycopgError as exc:
            raise WorkflowCheckpointUnavailableError from exc
        state = cast(RecommendationWorkflowState, snapshot.values)
        if not state:
            raise WorkflowNotFoundError(thread_id)
        return await self._result_from_snapshot(state, snapshot)

    async def resume(
        self,
        thread_id: str,
        command: WorkflowResumeCommand,
    ) -> WorkflowResult:
        """Resume exactly one paused checkpoint with a validated human command."""
        current = await self.status(thread_id)
        if current.phase is not WorkflowPhase.WAITING_FOR_HUMAN:
            raise WorkflowNotWaitingError(thread_id, current.phase.value)
        if (
            command.decision is HumanDecision.REVISE
            and current.revision_count >= self._maximum_revisions
        ):
            raise WorkflowRevisionLimitError(thread_id)
        if current.run_id is None:
            raise WorkflowStateError("A paused workflow has no GenerationRun ID.")

        await self._persistence.claim_resume(current.run_id)
        config = checkpoint_config(thread_id)
        try:
            await self._graph.ainvoke(
                Command(resume=command.model_dump(mode="json")),
                config=config,
                durability="sync",
            )
            return await self.status(thread_id)
        except PsycopgError as exc:
            await self._fail_from_checkpoint(thread_id, exc)
            raise WorkflowCheckpointUnavailableError from exc
        except Exception as exc:
            await self._fail_from_checkpoint(thread_id, exc)
            raise

    async def _result_from_snapshot(
        self,
        state: RecommendationWorkflowState,
        snapshot: StateSnapshot,
    ) -> WorkflowResult:
        phase = WorkflowPhase(state["phase"])
        run_id = UUID(state["run_id"]) if state.get("run_id") is not None else None
        run_status: RunStatus | None = None
        if run_id is not None:
            run_status = (await self._persistence.read(run_id)).status
        recommendation = (
            PromptRecommendation.model_validate(state["recommendation"])
            if state.get("recommendation") is not None
            else None
        )
        critique = (
            RecommendationCritique.model_validate(state["critique"])
            if state.get("critique") is not None
            else None
        )
        waiting = phase is WorkflowPhase.WAITING_FOR_HUMAN
        return WorkflowResult(
            workflow_id=state["workflow_id"],
            thread_id=state["thread_id"],
            checkpoint_id=_checkpoint_id(snapshot),
            run_id=run_id,
            run_status=run_status,
            phase=phase,
            waiting_for_human=waiting,
            revision_count=state.get("revision_count", 0),
            recommendation=recommendation,
            critique=critique,
            human_decision=(
                HumanDecision(state["human_decision"])
                if state.get("human_decision") is not None
                else None
            ),
            human_feedback=state.get("human_feedback"),
            interrupt=build_interrupt_payload(state) if waiting else None,
            error_code=state.get("error_code"),
        )

    async def _fail_from_checkpoint(self, thread_id: str, exc: Exception) -> None:
        """Best-effort failure audit that never replaces the original error."""
        try:
            snapshot = await self._graph.aget_state(checkpoint_config(thread_id))
            state = cast(RecommendationWorkflowState, snapshot.values)
            if not state or state.get("run_id") is None:
                return
            failed_state = cast(RecommendationWorkflowState, dict(state))
            failed_state["phase"] = WorkflowPhase.FAILED.value
            failed_state["error_code"] = _error_code(exc)
            failed_state["updated_at"] = datetime.now(UTC).isoformat()
            await self._persistence.fail(
                failed_state,
                error_code=_error_code(exc),
                latency_ms=_latency_ms(failed_state),
            )
            await self._graph.aupdate_state(
                checkpoint_config(thread_id),
                {
                    "phase": WorkflowPhase.FAILED.value,
                    "error_code": _error_code(exc),
                    "updated_at": failed_state["updated_at"],
                },
                as_node="fail_workflow",
            )
        except Exception:
            return


def _checkpoint_id(snapshot: StateSnapshot) -> str | None:
    configurable = snapshot.config.get("configurable", {})
    value = configurable.get("checkpoint_id")
    return str(value) if value is not None else None


def _error_code(exc: Exception) -> str:
    if isinstance(exc, RecommendationError):
        return exc.error_code
    if isinstance(exc, AlbaError):
        return exc.detail.error_code
    return "WORKFLOW_EXECUTION_FAILED"


def _latency_ms(state: RecommendationWorkflowState) -> int:
    started_at = datetime.fromisoformat(state["started_at"])
    return max(0, round((datetime.now(UTC) - started_at).total_seconds() * 1_000))
