"""Explicit input and safe view contracts for the local web application."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import GenerationStatus, QueryType, RunStatus
from app.recommendation.schemas import (
    BriefText,
    ConstraintText,
    ShortLabel,
)
from app.workflow.schemas import HumanDecision, HumanFeedback, ThreadId


class WebModel(BaseModel):
    """Immutable JSON-safe model used by templates and versioned API routes."""

    model_config = ConfigDict(frozen=True)


class WorkflowStartInput(WebModel):
    """One browser or API request to begin a durable workflow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: UUID
    query_type: QueryType
    brief: BriefText
    target_platform: ShortLabel | None = None
    generation_method: ShortLabel | None = None
    constraints: list[ConstraintText] = Field(default_factory=list, max_length=20)
    provider: Literal["fake", "ollama"] = "fake"
    thread_id: ThreadId | None = None


class WorkflowResumeInput(WebModel):
    """Closed browser or API command for an existing human-review pause."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: HumanDecision
    feedback: HumanFeedback | None = None

    @model_validator(mode="after")
    def validate_feedback_semantics(self) -> WorkflowResumeInput:
        """Keep browser and JSON commands consistent with the workflow contract."""
        if self.decision is HumanDecision.REVISE and self.feedback is None:
            raise ValueError("Human feedback is required when requesting a revision.")
        return self


class ProjectOptionView(WebModel):
    """A project safe to display in selects and links."""

    id: UUID
    name: str
    slug: str
    description: str | None = None


class FilterOptionView(WebModel):
    """One normalized, safe value rendered by a library filter select."""

    value: str
    label: str


class ConstraintView(WebModel):
    """One request constraint carrying its stable local identifier."""

    constraint_id: str
    text: str


class EvidenceView(WebModel):
    """One safe projection of retrieved evidence without an embedding vector."""

    example_id: UUID
    short_id: str
    status: GenerationStatus
    query_type: QueryType
    similarity: float
    summary: str
    rejection_reason: str | None = None
    warning: str | None = None


class CritiqueView(WebModel):
    """Deterministic critic data, never private model reasoning."""

    passed: bool
    hard_failures: list[str]
    review_reasons: list[str]
    warnings: list[str]
    recommended_route: str


class RecommendationView(WebModel):
    """Safe recommendation content intended for a reviewer."""

    recommended_prompt: str
    rationale: list[str]
    assumptions: list[str]
    confidence: float
    provider_confidence: float
    needs_human_review: bool
    covered_constraint_ids: list[str]
    unmet_constraint_ids: list[str]
    suggested_parameters: dict[str, object]
    negative_prompt: str | None = None


class WorkflowActionsView(WebModel):
    """Actions the current persisted state permits the reviewer to request."""

    can_approve: bool
    can_revise: bool
    can_reject: bool
    can_reconcile: bool


class WorkflowDetailView(WebModel):
    """Complete safe projection for HTML detail and JSON workflow reads."""

    workflow_id: str
    thread_id: str
    run_id: UUID | None
    checkpoint_id: str | None
    checkpoint_id_short: str | None
    project: ProjectOptionView
    query_type: QueryType | None
    target_platform: str | None
    generation_method: str | None
    provider: str
    model: str
    phase: str
    run_status: RunStatus | None
    workflow_outcome: str | None
    created_at: str
    completed_at: str | None
    brief: str
    constraints: list[ConstraintView]
    recommendation: RecommendationView | None
    approved_evidence: list[EvidenceView]
    rejected_evidence: list[EvidenceView]
    critique: CritiqueView | None
    revision_count: int
    human_decision: HumanDecision | None
    human_feedback: str | None
    waiting_for_human: bool
    error_code: str | None
    actions: WorkflowActionsView


class WorkflowStartResultView(WebModel):
    """Created or safely deduplicated workflow response."""

    workflow: WorkflowDetailView
    created: bool


class WorkflowListItemView(WebModel):
    """Bounded summary used by dashboard and paginated workflow history."""

    thread_id: str
    run_id: UUID
    project: ProjectOptionView
    brief_summary: str
    query_type: QueryType | None
    phase: str | None
    run_status: RunStatus
    workflow_outcome: str | None
    confidence: float | None
    provider: str
    revision_count: int
    waiting_for_human: bool
    created_at: str


class PaginationView(WebModel):
    """Simple bounded offset pagination metadata."""

    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    has_more: bool


class PaginationNavigationView(WebModel):
    """Safe navigation links and a range label for one rendered result page."""

    previous_url: str | None
    next_url: str | None
    range_label: str


class WorkflowListView(WebModel):
    """Workflow page payload shared by HTML and JSON."""

    items: list[WorkflowListItemView]
    pagination: PaginationView


class PromptExampleListItemView(WebModel):
    """Read-only prompt-library row without the raw pgvector value."""

    id: UUID
    project: ProjectOptionView
    prompt_summary: str
    expected_result_summary: str
    status: GenerationStatus
    query_type: QueryType
    target_platform: str
    generation_method: str
    tags: list[str]
    rejection_reason: str | None
    embedding_state: Literal["missing", "stale", "current"]
    created_at: str


class PromptExampleDetailView(WebModel):
    """Safe detail projection for one read-only corpus example."""

    id: UUID
    project: ProjectOptionView
    base_prompt: str
    expected_result: str
    generated_image_description: str | None
    status: GenerationStatus
    query_type: QueryType
    review_notes: str | None
    rejection_reason: str | None
    tags: list[str]
    target_platform: str
    generation_method: str
    embedding_provider: str | None
    embedding_model: str | None
    embedded_at: str | None
    embedding_state: Literal["missing", "stale", "current"]
    created_at: str
    updated_at: str


class PromptExampleListView(WebModel):
    """Prompt-library page payload with bounded offset pagination."""

    items: list[PromptExampleListItemView]
    pagination: PaginationView


class LibraryFilterOptionsView(WebModel):
    """Explicit read model for every selectable experience-library facet."""

    projects: list[ProjectOptionView]
    query_types: list[FilterOptionView]
    statuses: list[FilterOptionView]
    platforms: list[FilterOptionView]
    generation_methods: list[FilterOptionView]
    tags: list[FilterOptionView]


class DependencyStatusView(WebModel):
    """One non-secret dependency readiness observation."""

    name: str
    available: bool
    detail: str


class ReadinessView(WebModel):
    """Cached operational readiness projection; it is not a source of truth."""

    ready: bool
    checked_at: str
    dependencies: list[DependencyStatusView]


class ApiErrorView(WebModel):
    """Versioned JSON error envelope used only under `/api/v1`."""

    code: str
    message: str
    trace_id: str | None = None


class ApiErrorEnvelope(WebModel):
    """Stable versioned JSON error body without exception internals."""

    error: ApiErrorView
