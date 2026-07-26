"""Explicit LangGraph Graph API definition for recommendation review."""

# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from app.recommendation.schemas import (
    PromptRecommendation,
    RecommendationContext,
    RecommendationRequest,
)
from app.recommendation.service import RecommendationService
from app.workflow.critic import RecommendationCritic
from app.workflow.exceptions import WorkflowStateError
from app.workflow.persistence import WorkflowRunPersistence
from app.workflow.schemas import (
    CriticRoute,
    HumanDecision,
    RecommendationCritique,
    WorkflowInterruptPayload,
    WorkflowPhase,
    WorkflowResumeCommand,
)
from app.workflow.state import (
    RecommendationWorkflowState,
    RecommendationWorkflowUpdate,
)


class RecommendationWorkflowNodes:
    """Small graph nodes whose dependencies are runtime-only constructor inputs."""

    def __init__(
        self,
        recommendation_service: RecommendationService,
        persistence: WorkflowRunPersistence,
        *,
        critic: RecommendationCritic | None = None,
    ) -> None:
        self._recommendation_service = recommendation_service
        self._persistence = persistence
        self._critic = critic or RecommendationCritic()

    async def initialize_workflow(
        self,
        state: RecommendationWorkflowState,
    ) -> RecommendationWorkflowUpdate:
        """Create or recover the idempotent business run."""
        run_id = await self._persistence.initialize(state)
        return {
            "run_id": str(run_id),
            "phase": WorkflowPhase.RETRIEVING.value,
            "updated_at": _utc_now(),
        }

    async def retrieve_evidence(
        self,
        state: RecommendationWorkflowState,
    ) -> RecommendationWorkflowUpdate:
        """Reuse Stage 3's one-embedding retrieval operation."""
        request = RecommendationRequest.model_validate(state["request"])
        context = await self._recommendation_service.retrieve_context(request)
        return {
            "phase": WorkflowPhase.GENERATING.value,
            "recommendation_context": context.model_dump(mode="json"),
            "positive_evidence": [
                item.model_dump(mode="json") for item in context.positive_evidence
            ],
            "failure_evidence": [item.model_dump(mode="json") for item in context.failure_evidence],
            "updated_at": _utc_now(),
        }

    async def generate_recommendation(
        self,
        state: RecommendationWorkflowState,
    ) -> RecommendationWorkflowUpdate:
        """Reuse Stage 3's provider and grounding policy."""
        context_data = state["recommendation_context"]
        if context_data is None:
            raise WorkflowStateError("Recommendation context is missing before generation.")
        context = RecommendationContext.model_validate(context_data)
        recommendation = await self._recommendation_service.generate_from_context(context)
        return {
            "phase": WorkflowPhase.CRITIQUING.value,
            "recommendation": recommendation.model_dump(mode="json"),
            "updated_at": _utc_now(),
        }

    async def critique_recommendation(
        self,
        state: RecommendationWorkflowState,
    ) -> RecommendationWorkflowUpdate:
        """Apply deterministic defense-in-depth checks."""
        context_data = state["recommendation_context"]
        recommendation_data = state["recommendation"]
        if context_data is None or recommendation_data is None:
            raise WorkflowStateError("Critique requires context and recommendation.")
        context = RecommendationContext.model_validate(context_data)
        recommendation = PromptRecommendation.model_validate(recommendation_data)
        critique = self._critic.critique(recommendation, context)
        return {
            "critique": critique.model_dump(mode="json"),
            "updated_at": _utc_now(),
        }

    async def prepare_human_review(
        self,
        state: RecommendationWorkflowState,
    ) -> RecommendationWorkflowUpdate:
        """Persist safe review data before the side-effect-free interrupt node."""
        waiting_state = cast(RecommendationWorkflowState, dict(state))
        waiting_state["phase"] = WorkflowPhase.WAITING_FOR_HUMAN.value
        waiting_state["updated_at"] = _utc_now()
        await self._persistence.mark_waiting(
            waiting_state,
            latency_ms=_workflow_latency_ms(waiting_state),
        )
        return {
            "phase": WorkflowPhase.WAITING_FOR_HUMAN.value,
            "updated_at": waiting_state["updated_at"],
        }

    async def human_review(
        self,
        state: RecommendationWorkflowState,
    ) -> RecommendationWorkflowUpdate:
        """Pause without side effects and validate the resumed JSON command."""
        payload = build_interrupt_payload(state)
        raw_command = interrupt(payload.model_dump(mode="json"))
        command = WorkflowResumeCommand.model_validate(raw_command)
        return {
            "human_decision": command.decision.value,
            "human_feedback": command.feedback or state["human_feedback"],
            "updated_at": _utc_now(),
        }

    async def revise_recommendation(
        self,
        state: RecommendationWorkflowState,
    ) -> RecommendationWorkflowUpdate:
        """Generate the single allowed revision from original evidence and feedback."""
        context_data = state["recommendation_context"]
        recommendation_data = state["recommendation"]
        if context_data is None or recommendation_data is None:
            raise WorkflowStateError("Revision requires context and a prior recommendation.")
        context = RecommendationContext.model_validate(context_data)
        previous = PromptRecommendation.model_validate(recommendation_data)
        command = WorkflowResumeCommand.model_validate(
            {
                "decision": state["human_decision"],
                "feedback": state.get("human_feedback"),
            }
        )
        assert command.feedback is not None
        recommendation = await self._recommendation_service.revise_from_context(
            context,
            previous,
            command.feedback,
        )
        return {
            "phase": WorkflowPhase.CRITIQUING.value,
            "recommendation": recommendation.model_dump(mode="json"),
            "revision_count": state.get("revision_count", 0) + 1,
            "updated_at": _utc_now(),
        }

    async def complete_workflow(
        self,
        state: RecommendationWorkflowState,
    ) -> RecommendationWorkflowUpdate:
        """Persist an approved terminal decision."""
        completed_state = cast(RecommendationWorkflowState, dict(state))
        completed_state["phase"] = WorkflowPhase.COMPLETED.value
        completed_state["updated_at"] = _utc_now()
        await self._persistence.complete(
            completed_state,
            outcome=HumanDecision.APPROVE.value,
            latency_ms=_workflow_latency_ms(completed_state),
        )
        return {
            "phase": WorkflowPhase.COMPLETED.value,
            "updated_at": completed_state["updated_at"],
        }

    async def reject_workflow(
        self,
        state: RecommendationWorkflowState,
    ) -> RecommendationWorkflowUpdate:
        """Persist human rejection as a completed business process, not a failure."""
        rejected_state = cast(RecommendationWorkflowState, dict(state))
        rejected_state["phase"] = WorkflowPhase.COMPLETED.value
        rejected_state["updated_at"] = _utc_now()
        await self._persistence.complete(
            rejected_state,
            outcome=HumanDecision.REJECT.value,
            latency_ms=_workflow_latency_ms(rejected_state),
        )
        return {
            "phase": WorkflowPhase.COMPLETED.value,
            "updated_at": rejected_state["updated_at"],
        }

    async def fail_workflow(
        self,
        state: RecommendationWorkflowState,
    ) -> RecommendationWorkflowUpdate:
        """Persist a deterministic hard-critic failure."""
        failed_state = cast(RecommendationWorkflowState, dict(state))
        failed_state["phase"] = WorkflowPhase.FAILED.value
        failed_state["error_code"] = "WORKFLOW_CRITIC_HARD_FAILURE"
        failed_state["updated_at"] = _utc_now()
        await self._persistence.fail(
            failed_state,
            error_code="WORKFLOW_CRITIC_HARD_FAILURE",
            latency_ms=_workflow_latency_ms(failed_state),
        )
        return {
            "phase": WorkflowPhase.FAILED.value,
            "error_code": "WORKFLOW_CRITIC_HARD_FAILURE",
            "updated_at": failed_state["updated_at"],
        }


def route_after_critique(
    state: RecommendationWorkflowState,
) -> Literal["prepare_human_review", "fail_workflow"]:
    """Route only from the typed deterministic critic result."""
    critique_data = state["critique"]
    if critique_data is None:
        raise WorkflowStateError("Critic routing requires a critique result.")
    critique = RecommendationCritique.model_validate(critique_data)
    if critique.recommended_route is CriticRoute.HARD_FAILURE:
        return "fail_workflow"
    return "prepare_human_review"


def route_after_human(
    state: RecommendationWorkflowState,
) -> Literal["complete_workflow", "reject_workflow", "revise_recommendation"]:
    """Route only from the closed human decision enum."""
    decision_value = state["human_decision"]
    if decision_value is None:
        raise WorkflowStateError("Human routing requires a decision.")
    decision = HumanDecision(decision_value)
    if decision is HumanDecision.APPROVE:
        return "complete_workflow"
    if decision is HumanDecision.REJECT:
        return "reject_workflow"
    return "revise_recommendation"


def compile_recommendation_workflow(
    nodes: RecommendationWorkflowNodes,
    checkpointer: AsyncPostgresSaver,
) -> CompiledStateGraph[
    RecommendationWorkflowState,
    None,
    RecommendationWorkflowState,
    RecommendationWorkflowState,
]:
    """Compile the explicit Graph API with durable PostgreSQL checkpoints."""
    builder = StateGraph(RecommendationWorkflowState)
    builder.add_node("initialize_workflow", nodes.initialize_workflow)
    builder.add_node("retrieve_evidence", nodes.retrieve_evidence)
    builder.add_node("generate_recommendation", nodes.generate_recommendation)
    builder.add_node("critique_recommendation", nodes.critique_recommendation)
    builder.add_node("prepare_human_review", nodes.prepare_human_review)
    builder.add_node("human_review", nodes.human_review)
    builder.add_node("revise_recommendation", nodes.revise_recommendation)
    builder.add_node("complete_workflow", nodes.complete_workflow)
    builder.add_node("reject_workflow", nodes.reject_workflow)
    builder.add_node("fail_workflow", nodes.fail_workflow)

    builder.add_edge(START, "initialize_workflow")
    builder.add_edge("initialize_workflow", "retrieve_evidence")
    builder.add_edge("retrieve_evidence", "generate_recommendation")
    builder.add_edge("generate_recommendation", "critique_recommendation")
    builder.add_conditional_edges("critique_recommendation", route_after_critique)
    builder.add_edge("prepare_human_review", "human_review")
    builder.add_conditional_edges("human_review", route_after_human)
    builder.add_edge("revise_recommendation", "critique_recommendation")
    builder.add_edge("complete_workflow", END)
    builder.add_edge("reject_workflow", END)
    builder.add_edge("fail_workflow", END)
    return builder.compile(
        checkpointer=checkpointer,
        name="alba_recommendation_review",
    )


def build_interrupt_payload(
    state: RecommendationWorkflowState,
) -> WorkflowInterruptPayload:
    """Build the only information exposed to a human reviewer."""
    recommendation_data = state["recommendation"]
    critique_data = state["critique"]
    context_data = state["recommendation_context"]
    run_id = state["run_id"]
    if (
        recommendation_data is None
        or critique_data is None
        or context_data is None
        or run_id is None
    ):
        raise WorkflowStateError("A review interrupt requires complete safe review state.")
    recommendation = PromptRecommendation.model_validate(recommendation_data)
    critique = RecommendationCritique.model_validate(critique_data)
    context = RecommendationContext.model_validate(context_data)
    return WorkflowInterruptPayload(
        workflow_id=state["workflow_id"],
        thread_id=state["thread_id"],
        run_id=UUID(run_id),
        recommended_prompt=recommendation.recommended_prompt,
        rationale=recommendation.rationale,
        constraints=recommendation.constraints,
        covered_constraint_ids=recommendation.covered_constraint_ids,
        unmet_constraint_ids=recommendation.unmet_constraint_ids,
        positive_evidence=context.positive_evidence,
        failure_evidence=context.failure_evidence,
        failure_warnings=[
            {
                "evidence_id": str(item.evidence_id),
                "warning": item.warning,
            }
            for item in recommendation.failure_warnings
        ],
        confidence=recommendation.confidence,
        critic=critique,
        revision_count=state.get("revision_count", 0),
        options=list(HumanDecision),
    )


def _workflow_latency_ms(state: RecommendationWorkflowState) -> int:
    started_at = datetime.fromisoformat(state["started_at"])
    return max(0, round((datetime.now(UTC) - started_at).total_seconds() * 1_000))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
