"""Start, inspect, and resume durable recommendation workflows."""

# pyright: reportUnknownMemberType=false

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command, StateSnapshot
from psycopg import Error as PsycopgError
from pydantic import JsonValue, TypeAdapter

from app.core.exceptions import AlbaError
from app.domain.enums import RunStatus
from app.domain.exceptions import EntityNotFoundError, InvalidRunTransitionError
from app.recommendation.exceptions import RecommendationError
from app.recommendation.schemas import PromptRecommendation, RecommendationRequest
from app.recommendation.service import RecommendationService
from app.workflow.checkpoint import checkpoint_config
from app.workflow.exceptions import (
    WorkflowAlreadyExistsError,
    WorkflowCheckpointUnavailableError,
    WorkflowNotFoundError,
    WorkflowNotWaitingError,
    WorkflowResumeNotAcceptedError,
    WorkflowResumeReconciliationRejectedError,
    WorkflowResumeReconciliationRequiredError,
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

logger = logging.getLogger(__name__)


class RecommendationWorkflowService:
    """Public durable workflow use cases around one compiled StateGraph."""

    def __init__(
        self,
        checkpointer: AsyncPostgresSaver,
        recommendation_service: RecommendationService,
        persistence: WorkflowRunPersistence,
        *,
        maximum_revisions: int = 1,
        diagnostics_enabled: bool = False,
    ) -> None:
        if maximum_revisions != 1:
            raise ValueError("Stage 4 supports exactly one human-requested revision.")
        self._checkpointer = checkpointer
        self._persistence = persistence
        self._maximum_revisions = maximum_revisions
        self._diagnostics_enabled = diagnostics_enabled
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
        thread_id = _normalize_thread_id(thread_id)
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
        thread_id = _normalize_thread_id(thread_id)
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
        if current.run_status is RunStatus.RUNNING:
            raise WorkflowResumeReconciliationRequiredError(thread_id)
        if current.run_status is not RunStatus.WAITING_FOR_HUMAN:
            raise WorkflowResumeReconciliationRejectedError(thread_id)
        if current.checkpoint_id is None:
            raise WorkflowStateError("A paused workflow has no checkpoint ID.")

        config = checkpoint_config(thread_id)
        await self._persistence.claim_resume(current.run_id)
        try:
            await self._invoke_resume_graph(command, config)
            result = await self.status(thread_id)
            await self._assert_resume_invariant(command, result)
            return result
        except PsycopgError as exc:
            if await self._reconcile_or_fail_resume(
                thread_id,
                current.checkpoint_id,
                exc,
            ):
                raise WorkflowResumeNotAcceptedError(thread_id) from exc
            raise WorkflowCheckpointUnavailableError from exc
        except Exception as exc:
            if await self._reconcile_or_fail_resume(
                thread_id,
                current.checkpoint_id,
                exc,
            ):
                raise WorkflowResumeNotAcceptedError(thread_id) from exc
            raise

    async def reconcile_unaccepted_resume(self, thread_id: str) -> WorkflowResult:
        """Release only the documented paused-checkpoint/running-run split state."""
        thread_id = _normalize_thread_id(thread_id)
        config = checkpoint_config(thread_id)
        try:
            snapshot = await self._graph.aget_state(config)
        except PsycopgError as exc:
            raise WorkflowCheckpointUnavailableError from exc
        state = cast(RecommendationWorkflowState, snapshot.values)
        if not state or not _is_unaccepted_resume_state(state):
            raise WorkflowResumeReconciliationRejectedError(thread_id)
        checkpoint_id = _checkpoint_id(snapshot)
        run_id_text = state.get("run_id")
        if checkpoint_id is None or run_id_text is None:
            raise WorkflowResumeReconciliationRejectedError(thread_id)
        run = await self._persistence.read(UUID(run_id_text))
        if run.status is not RunStatus.RUNNING:
            raise WorkflowResumeReconciliationRejectedError(thread_id)
        try:
            await self._persistence.reconcile_unaccepted_resume(
                state,
                checkpoint_id=checkpoint_id,
            )
        except (InvalidRunTransitionError, EntityNotFoundError) as exc:
            raise WorkflowResumeReconciliationRejectedError(thread_id) from exc
        reconciled = await self.status(thread_id)
        if (
            reconciled.phase is not WorkflowPhase.WAITING_FOR_HUMAN
            or reconciled.run_status is not RunStatus.WAITING_FOR_HUMAN
            or reconciled.human_decision is not None
        ):
            raise WorkflowStateError("Resume reconciliation did not restore the paused invariant.")
        self._diagnostic(
            "workflow resume reconciled",
            thread_id=thread_id,
            run_id=str(run.id),
            error_code="WORKFLOW_RESUME_NOT_ACCEPTED",
        )
        return reconciled

    async def _invoke_resume_graph(
        self,
        command: WorkflowResumeCommand,
        config: RunnableConfig,
    ) -> None:
        """Invoke LangGraph behind a narrow seam for resume-failure regression tests."""
        await self._graph.ainvoke(
            Command(resume=command.model_dump(mode="json")),
            config=config,
            durability="sync",
        )

    async def _assert_resume_invariant(
        self,
        command: WorkflowResumeCommand,
        result: WorkflowResult,
    ) -> None:
        """Verify the business run and checkpoint agree after a successful resume."""
        if result.run_id is None or result.run_status is None:
            raise WorkflowStateError("A resumed workflow has no GenerationRun state.")
        run = await self._persistence.read(result.run_id)
        expected_outcome = command.decision.value
        if command.decision is HumanDecision.REVISE:
            valid = (
                result.phase is WorkflowPhase.WAITING_FOR_HUMAN
                and result.run_status is RunStatus.WAITING_FOR_HUMAN
                and result.revision_count == 1
                and result.human_decision is HumanDecision.REVISE
            )
        else:
            valid = (
                result.phase is WorkflowPhase.COMPLETED
                and result.run_status is RunStatus.COMPLETED
                and result.human_decision is command.decision
                and run.provider_parameters.get("workflow_outcome") == expected_outcome
            )
        if not valid:
            raise WorkflowStateError("Checkpoint and GenerationRun disagree after resume.")

    async def _reconcile_or_fail_resume(
        self,
        thread_id: str,
        claimed_checkpoint_id: str,
        exc: Exception,
    ) -> bool:
        """Roll back a claim only when the checkpointer proves it never accepted it."""
        try:
            snapshot = await self._graph.aget_state(checkpoint_config(thread_id))
            state = cast(RecommendationWorkflowState, snapshot.values)
            checkpoint_id = _checkpoint_id(snapshot)
            if (
                state
                and checkpoint_id == claimed_checkpoint_id
                and _is_unaccepted_resume_state(state)
            ):
                assert checkpoint_id is not None
                await self._persistence.reconcile_unaccepted_resume(
                    state,
                    checkpoint_id=checkpoint_id,
                )
                self._diagnostic(
                    "workflow resume was not accepted and was reconciled",
                    thread_id=thread_id,
                    run_id=state.get("run_id"),
                    error_code=_error_code(exc),
                )
                return True
        except Exception as reconciliation_exc:
            self._diagnostic(
                "workflow resume reconciliation could not run",
                thread_id=thread_id,
                run_id=None,
                error_code=_error_code(reconciliation_exc),
            )
        await self._fail_from_checkpoint(thread_id, exc)
        return False

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

    async def _fail_from_checkpoint(self, thread_id: str, exc: Exception) -> bool:
        """Persist a coherent accepted-execution failure without replacing its cause."""
        try:
            snapshot = await self._graph.aget_state(checkpoint_config(thread_id))
            state = cast(RecommendationWorkflowState, snapshot.values)
            if not state or state.get("run_id") is None:
                return False
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
            return True
        except Exception as compensation_exc:
            self._diagnostic(
                "workflow failure compensation could not complete",
                thread_id=thread_id,
                run_id=None,
                error_code=_error_code(compensation_exc),
            )
            return False

    def _diagnostic(
        self,
        message: str,
        *,
        thread_id: str,
        run_id: str | None,
        error_code: str,
    ) -> None:
        """Emit bounded local diagnostics without exception text or secrets."""
        if self._diagnostics_enabled:
            logger.info(
                "%s thread_id=%s run_id=%s error_code=%s",
                message,
                thread_id,
                run_id,
                error_code,
            )


def _checkpoint_id(snapshot: StateSnapshot) -> str | None:
    configurable = snapshot.config.get("configurable", {})
    value = configurable.get("checkpoint_id")
    return str(value) if value is not None else None


def _normalize_thread_id(thread_id: str) -> str:
    """Validate and normalize one durable thread identifier exactly once."""
    return cast(str, TypeAdapter(ThreadId).validate_python(thread_id))


def _is_unaccepted_resume_state(state: RecommendationWorkflowState) -> bool:
    """Return whether a checkpoint still proves no human command was accepted."""
    return (
        state.get("phase") == WorkflowPhase.WAITING_FOR_HUMAN.value
        and state.get("human_decision") is None
    )


def _error_code(exc: Exception) -> str:
    if isinstance(exc, RecommendationError):
        return exc.error_code
    if isinstance(exc, AlbaError):
        return exc.detail.error_code
    return "WORKFLOW_EXECUTION_FAILED"


def _latency_ms(state: RecommendationWorkflowState) -> int:
    started_at = datetime.fromisoformat(state["started_at"])
    return max(0, round((datetime.now(UTC) - started_at).total_seconds() * 1_000))
