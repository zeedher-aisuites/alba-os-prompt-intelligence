"""Validated contracts for durable recommendation workflows."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.domain.enums import RunStatus
from app.recommendation.schemas import (
    ConstraintReference,
    EvidenceReference,
    PromptRecommendation,
    RecommendationRequest,
)

WorkflowId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
ThreadId = WorkflowId
HumanFeedback = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000),
]
SafeMessage = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


class WorkflowPhase(StrEnum):
    """Deterministic phases persisted in LangGraph state."""

    INITIALIZING = "initializing"
    RETRIEVING = "retrieving"
    GENERATING = "generating"
    CRITIQUING = "critiquing"
    WAITING_FOR_HUMAN = "waiting_for_human"
    REVISING = "revising"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"


class HumanDecision(StrEnum):
    """Closed human-review command vocabulary."""

    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"


class CriticRoute(StrEnum):
    """Routes selected by the deterministic critic."""

    HUMAN_REVIEW = "human_review"
    HARD_FAILURE = "hard_failure"


class RecommendationCritique(BaseModel):
    """Deterministic validation findings; never model-authored reasoning."""

    model_config = ConfigDict(frozen=True)

    passed: bool
    hard_failures: list[SafeMessage] = Field(default_factory=list, max_length=20)
    review_reasons: list[SafeMessage] = Field(default_factory=list, max_length=20)
    warnings: list[SafeMessage] = Field(default_factory=list, max_length=20)
    recommended_route: CriticRoute


class WorkflowResumeCommand(BaseModel):
    """Strict JSON payload accepted by `Command(resume=...)`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: HumanDecision
    feedback: HumanFeedback | None = None

    @model_validator(mode="after")
    def validate_feedback_semantics(self) -> WorkflowResumeCommand:
        """Require feedback only where it has defined workflow semantics."""
        if self.decision is HumanDecision.REVISE and self.feedback is None:
            raise ValueError("Human feedback is required when requesting a revision.")
        return self


class WorkflowInterruptPayload(BaseModel):
    """Safe, JSON-only review packet surfaced at an interrupt."""

    model_config = ConfigDict(frozen=True)

    workflow_id: WorkflowId
    thread_id: ThreadId
    run_id: UUID
    recommended_prompt: str
    rationale: list[str]
    constraints: list[ConstraintReference]
    covered_constraint_ids: list[str]
    unmet_constraint_ids: list[str]
    positive_evidence: list[EvidenceReference]
    failure_evidence: list[EvidenceReference]
    failure_warnings: list[dict[str, str]]
    confidence: float = Field(ge=0, le=1)
    critic: RecommendationCritique
    revision_count: int = Field(ge=0, le=1)
    options: list[HumanDecision]


class WorkflowStart(BaseModel):
    """Validated initial graph input before serialization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: WorkflowId
    thread_id: ThreadId
    request: RecommendationRequest


class WorkflowResult(BaseModel):
    """Public start, status, or resume result."""

    model_config = ConfigDict(frozen=True)

    workflow_id: WorkflowId
    thread_id: ThreadId
    checkpoint_id: str | None
    run_id: UUID | None
    run_status: RunStatus | None
    phase: WorkflowPhase
    waiting_for_human: bool
    revision_count: int = Field(ge=0, le=1)
    recommendation: PromptRecommendation | None = None
    critique: RecommendationCritique | None = None
    human_decision: HumanDecision | None = None
    human_feedback: str | None = None
    interrupt: WorkflowInterruptPayload | None = None
    error_code: str | None = None


class WorkflowEvaluationCase(BaseModel):
    """One deterministic workflow evaluation scenario."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    expected_decision: HumanDecision | None
    expects_revision: bool = False
    expects_failure: bool = False


class WorkflowEvaluationObservation(BaseModel):
    """Measured objective outcomes for one executed workflow."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    checkpoint_persisted: bool
    resume_expected: bool
    resume_succeeded: bool
    transition_valid: bool
    duplicate_terminal_decision: bool
    feedback_expected: bool
    feedback_incorporated: bool
    failure_expected: bool
    failed_run_persisted: bool
    latency_to_interrupt_ms: int = Field(ge=0)
    latency_after_resume_ms: int = Field(ge=0)


class WorkflowEvaluationReport(BaseModel):
    """Objective Stage 4 workflow metrics."""

    model_config = ConfigDict(frozen=True)

    label: str
    case_count: int = Field(ge=0)
    checkpoint_persistence_rate: float = Field(ge=0, le=1)
    successful_resume_rate: float = Field(ge=0, le=1)
    valid_transition_rate: float = Field(ge=0, le=1)
    duplicate_terminal_decision_rate: float = Field(ge=0, le=1)
    human_feedback_incorporation_rate: float = Field(ge=0, le=1)
    failed_run_persistence_rate: float = Field(ge=0, le=1)
    latency_to_interrupt_p50_ms: float = Field(ge=0)
    latency_after_resume_p50_ms: float = Field(ge=0)
