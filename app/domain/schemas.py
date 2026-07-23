"""Pydantic input and output contracts for persistent entities."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
)

from app.domain.enums import GenerationStatus, QueryType, RunStatus

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Slug = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ShortLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Score = Annotated[Decimal, Field(ge=0, le=1, max_digits=4, decimal_places=3)]
NonNegativeCost = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=4)]
NonNegativeLatency = Annotated[int, Field(ge=0)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


def normalize_utc(value: datetime) -> datetime:
    """Normalize every accepted aware timestamp to UTC."""
    return value.astimezone(UTC)


UtcDatetime = Annotated[AwareDatetime, AfterValidator(normalize_utc)]


class ReadModel(BaseModel):
    """Shared ORM-to-contract configuration."""

    model_config = ConfigDict(from_attributes=True, frozen=True)


class ProjectCreate(BaseModel):
    """Validated input for a new project."""

    model_config = ConfigDict(frozen=True)

    name: Name
    slug: Slug
    description: str | None = None


class ProjectUpdate(BaseModel):
    """Validated partial update for a project."""

    model_config = ConfigDict(frozen=True)

    name: Name | None = None
    slug: Slug | None = None
    description: str | None = None


class ProjectRead(ReadModel):
    """Public project representation."""

    id: UUID
    name: str
    slug: str
    description: str | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class PromptExampleCreate(BaseModel):
    """Validated input for a prompt example."""

    model_config = ConfigDict(frozen=True)

    project_id: UUID
    base_prompt: NonEmptyText
    expected_result: NonEmptyText
    generated_image_description: str | None = None
    generation_method: ShortLabel
    target_platform: ShortLabel
    query_type: QueryType
    status: GenerationStatus = GenerationStatus.IN_REVIEW
    review_notes: str | None = None
    rejection_reason: str | None = None
    quality_score: Score | None = None
    image_path: str | None = None
    image_sha256: Sha256 | None = None
    tags: list[Tag] = Field(default_factory=list)
    embedding_text: NonEmptyText


class PromptExampleUpdate(BaseModel):
    """Validated partial update for a prompt example."""

    model_config = ConfigDict(frozen=True)

    base_prompt: NonEmptyText | None = None
    expected_result: NonEmptyText | None = None
    generated_image_description: str | None = None
    generation_method: ShortLabel | None = None
    target_platform: ShortLabel | None = None
    query_type: QueryType | None = None
    status: GenerationStatus | None = None
    review_notes: str | None = None
    rejection_reason: str | None = None
    quality_score: Score | None = None
    image_path: str | None = None
    image_sha256: Sha256 | None = None
    tags: list[Tag] | None = None
    embedding_text: NonEmptyText | None = None


class PromptExampleRead(ReadModel):
    """Public prompt example representation without raw vector data."""

    id: UUID
    project_id: UUID
    base_prompt: str
    expected_result: str
    generated_image_description: str | None
    generation_method: str
    target_platform: str
    query_type: QueryType
    status: GenerationStatus
    review_notes: str | None
    rejection_reason: str | None
    quality_score: Decimal | None
    image_path: str | None
    image_sha256: str | None
    tags: list[str]
    embedding_text: str
    created_at: UtcDatetime
    updated_at: UtcDatetime


class HumanReviewCreate(BaseModel):
    """Validated input for a human review."""

    model_config = ConfigDict(frozen=True)

    prompt_example_id: UUID
    overall_score: Score
    prompt_adherence_score: Score
    identity_consistency_score: Score
    outfit_fidelity_score: Score
    composition_score: Score
    physical_coherence_score: Score
    continuity_score: Score
    strengths: list[NonEmptyText] = Field(default_factory=list)
    problems: list[NonEmptyText] = Field(default_factory=list)
    recommendations: list[NonEmptyText] = Field(default_factory=list)
    final_status: GenerationStatus


class HumanReviewRead(ReadModel):
    """Public human review representation."""

    id: UUID
    prompt_example_id: UUID
    overall_score: Decimal
    prompt_adherence_score: Decimal
    identity_consistency_score: Decimal
    outfit_fidelity_score: Decimal
    composition_score: Decimal
    physical_coherence_score: Decimal
    continuity_score: Decimal
    strengths: list[str]
    problems: list[str]
    recommendations: list[str]
    final_status: GenerationStatus
    created_at: UtcDatetime


class GenerationRunCreate(BaseModel):
    """Validated input for a placeholder generation run."""

    model_config = ConfigDict(frozen=True)

    project_id: UUID
    brief_text: NonEmptyText
    prompt_recommendation: dict[str, JsonValue]
    provider: ShortLabel
    model: ShortLabel
    generation_method: ShortLabel
    provider_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    status: RunStatus = RunStatus.PENDING
    estimated_cost_usd: NonNegativeCost | None = None
    latency_ms: NonNegativeLatency | None = None
    error_code: str | None = None
    trace_id: str | None = None
    completed_at: UtcDatetime | None = None


class GenerationRunRead(ReadModel):
    """Public generation run representation."""

    id: UUID
    project_id: UUID
    brief_text: str
    prompt_recommendation: dict[str, JsonValue]
    provider: str
    model: str
    generation_method: str
    provider_parameters: dict[str, JsonValue]
    status: RunStatus
    estimated_cost_usd: Decimal | None
    latency_ms: int | None
    error_code: str | None
    trace_id: str | None
    created_at: UtcDatetime
    completed_at: UtcDatetime | None
