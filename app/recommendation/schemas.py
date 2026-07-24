"""Typed recommendation input, context, provider output, and result contracts."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
)

from app.domain.enums import GenerationStatus, QueryType, RunStatus

BriefText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000),
]
ConstraintText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
RecommendationText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=16_000),
]
ShortOutputText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1_200),
]
EvidenceSummary = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
ShortLabel = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]
TraceId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=32),
]
ConstraintId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=2,
        max_length=8,
        pattern=r"^C[1-9][0-9]*$",
    ),
]


class RecommendationRequest(BaseModel):
    """Validated request for one recommendation; query type remains explicit."""

    model_config = ConfigDict(frozen=True)

    project_id: UUID
    brief: BriefText
    query_type: QueryType
    target_platform: ShortLabel | None = None
    generation_method: ShortLabel | None = None
    constraints: list[ConstraintText] = Field(default_factory=list, max_length=20)
    positive_limit: int = Field(default=5, ge=1, le=10)
    failure_limit: int = Field(default=5, ge=1, le=10)
    minimum_similarity: float | None = Field(default=None, ge=-1, le=1)
    trace_id: TraceId | None = None

    @field_validator("constraints")
    @classmethod
    def constraints_must_be_unique(cls, values: list[str]) -> list[str]:
        """Reject ambiguous repeated constraints after whitespace normalization."""
        if len({value.casefold() for value in values}) != len(values):
            raise ValueError("Constraints must be unique.")
        return values


class EvidenceReference(BaseModel):
    """Safe evidence metadata without ORM state or vector data."""

    model_config = ConfigDict(frozen=True)

    example_id: UUID
    status: GenerationStatus
    query_type: QueryType
    similarity: float = Field(ge=-1, le=1)
    summary: EvidenceSummary
    rejection_reason: ShortOutputText | None = None


class ConstraintReference(BaseModel):
    """Stable request constraint presented to the provider by identifier."""

    model_config = ConfigDict(frozen=True)

    constraint_id: ConstraintId
    text: ConstraintText


class FailureWarning(BaseModel):
    """A warning grounded in one retrieved rejected example."""

    model_config = ConfigDict(frozen=True)

    evidence_id: UUID
    warning: ShortOutputText


class RecommendationDraft(BaseModel):
    """Structured content that a recommendation provider is allowed to author."""

    model_config = ConfigDict(frozen=True)

    recommended_prompt: RecommendationText
    rationale: list[ShortOutputText] = Field(min_length=1, max_length=8)
    used_positive_evidence_ids: list[UUID] = Field(max_length=10)
    failure_warnings: list[FailureWarning] = Field(
        max_length=10,
    )
    covered_constraint_ids: list[ConstraintId] = Field(max_length=20)
    unmet_constraint_ids: list[ConstraintId] = Field(max_length=20)
    assumptions: list[ShortOutputText] = Field(default_factory=list, max_length=10)
    provider_confidence: float = Field(ge=0, le=1)
    needs_human_review: bool
    platform_notes: ShortOutputText | None = None
    suggested_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    negative_prompt: RecommendationText | None = None

    @field_validator("used_positive_evidence_ids")
    @classmethod
    def evidence_ids_must_be_unique(cls, values: list[UUID]) -> list[UUID]:
        """Make evidence references unambiguous."""
        if len(set(values)) != len(values):
            raise ValueError("Evidence IDs must be unique.")
        return values

    @field_validator("covered_constraint_ids", "unmet_constraint_ids")
    @classmethod
    def constraint_ids_must_be_unique(cls, values: list[str]) -> list[str]:
        """Reject duplicate accounting entries within either constraint list."""
        if len(set(values)) != len(values):
            raise ValueError("Constraint IDs must be unique.")
        return values

    @field_validator("failure_warnings")
    @classmethod
    def warning_evidence_ids_must_be_unique(
        cls,
        values: list[FailureWarning],
    ) -> list[FailureWarning]:
        """Avoid contradictory parallel warnings for the same rejected example."""
        identifiers = [item.evidence_id for item in values]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Failure warning evidence IDs must be unique.")
        return values


class PromptRecommendation(RecommendationDraft):
    """Application-stamped recommendation returned and persisted publicly."""

    constraints: list[ConstraintReference]
    confidence: float = Field(ge=0, le=1)
    repair_attempts_used: int = Field(ge=0, le=1)
    provider: ShortLabel
    model: ShortLabel


class RecommendationContext(BaseModel):
    """Deterministic provider input containing only bounded, untrusted data."""

    model_config = ConfigDict(frozen=True)

    system_prompt: str
    user_prompt: str
    request: RecommendationRequest
    constraints: list[ConstraintReference]
    positive_evidence: list[EvidenceReference]
    failure_evidence: list[EvidenceReference]
    omitted_positive_evidence: int = Field(ge=0)
    omitted_failure_evidence: int = Field(ge=0)


class RecommendationResult(BaseModel):
    """Completed run plus the evidence visible to the provider."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    status: RunStatus
    recommendation: PromptRecommendation
    positive_evidence: list[EvidenceReference]
    failure_evidence: list[EvidenceReference]
    latency_ms: int = Field(ge=0)
