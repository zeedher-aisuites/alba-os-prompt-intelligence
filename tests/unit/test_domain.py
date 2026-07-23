"""Unit tests for Stage 1 domain contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from app.core.exceptions import AlbaError
from app.domain.enums import GenerationStatus, QueryType, RunStatus
from app.domain.exceptions import (
    ConstraintViolationError,
    DatabaseUnavailableError,
    DuplicateSlugError,
    EntityNotFoundError,
)
from app.domain.schemas import (
    GenerationRunCreate,
    HumanReviewCreate,
    ProjectRead,
    ProjectUpdate,
    PromptExampleCreate,
)
from pydantic import ValidationError


def test_enum_values_are_stable() -> None:
    assert [item.value for item in QueryType] == [
        "ai_influencer",
        "toon",
        "product_brand",
        "marketing",
        "logo",
        "video_frame",
        "art",
        "other",
    ]
    assert [item.value for item in GenerationStatus] == [
        "approved",
        "in_review",
        "rejected",
    ]
    assert [item.value for item in RunStatus] == [
        "pending",
        "running",
        "waiting_for_human",
        "completed",
        "failed",
    ]


def test_project_update_tracks_only_supplied_fields() -> None:
    update = ProjectUpdate(name="Renamed")

    assert update.model_dump(exclude_unset=True) == {"name": "Renamed"}


def test_project_read_requires_timezone_aware_dates() -> None:
    now = datetime.now(UTC)
    project = ProjectRead(
        id=uuid4(),
        name="Project",
        slug="project",
        description=None,
        created_at=now,
        updated_at=now,
    )
    assert project.created_at.tzinfo is UTC

    with pytest.raises(ValidationError):
        ProjectRead(
            id=uuid4(),
            name="Project",
            slug="project",
            description=None,
            created_at=datetime(2026, 1, 1),
            updated_at=now,
        )


def test_project_read_normalizes_aware_dates_to_utc() -> None:
    plus_two = timezone(timedelta(hours=2))
    source = datetime(2026, 1, 1, 12, 0, tzinfo=plus_two)

    project = ProjectRead(
        id=uuid4(),
        name="Project",
        slug="project",
        description=None,
        created_at=source,
        updated_at=source,
    )

    assert project.created_at == datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    assert project.created_at.tzinfo is UTC


def test_prompt_example_rejects_out_of_range_quality_score() -> None:
    with pytest.raises(ValidationError):
        PromptExampleCreate(
            project_id=uuid4(),
            base_prompt="Prompt",
            expected_result="Expected",
            generation_method="text_to_image",
            target_platform="manual_other",
            query_type=QueryType.OTHER,
            quality_score=Decimal("1.001"),
            embedding_text="Source text",
        )


def test_human_review_rejects_out_of_range_scores() -> None:
    with pytest.raises(ValidationError):
        HumanReviewCreate(
            prompt_example_id=uuid4(),
            overall_score=Decimal("-0.001"),
            prompt_adherence_score=Decimal("0.500"),
            identity_consistency_score=Decimal("0.500"),
            outfit_fidelity_score=Decimal("0.500"),
            composition_score=Decimal("0.500"),
            physical_coherence_score=Decimal("0.500"),
            continuity_score=Decimal("0.500"),
            final_status=GenerationStatus.REJECTED,
        )


def test_generation_run_rejects_negative_cost_and_latency() -> None:
    with pytest.raises(ValidationError):
        GenerationRunCreate(
            project_id=uuid4(),
            brief_text="A brief",
            prompt_recommendation={"prompt": "A prompt"},
            provider="mock",
            model="mock-v1",
            generation_method="text_to_image",
            estimated_cost_usd=Decimal("-0.0001"),
            latency_ms=-1,
        )


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (EntityNotFoundError("Project", "missing"), "ENTITY_NOT_FOUND", False),
        (DuplicateSlugError("duplicate"), "DUPLICATE_PROJECT_SLUG", False),
        (ConstraintViolationError("project"), "CONSTRAINT_VIOLATION", False),
        (DatabaseUnavailableError(), "DATABASE_UNAVAILABLE", True),
    ],
)
def test_domain_errors_have_stable_details(
    error: AlbaError,
    code: str,
    retryable: bool,
) -> None:
    detail = error.detail
    assert detail.error_code == code
    assert detail.retryable is retryable
