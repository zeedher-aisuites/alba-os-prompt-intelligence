"""Recommendation request and output schema validation."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.domain.enums import QueryType
from app.recommendation.schemas import (
    FailureWarning,
    RecommendationDraft,
    RecommendationRequest,
)
from pydantic import ValidationError


def request_data() -> dict[str, object]:
    return {
        "project_id": uuid4(),
        "brief": "Preserve the virtual host identity.",
        "query_type": QueryType.AI_INFLUENCER,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("brief", ""),
        ("brief", "x" * 4_001),
        ("positive_limit", 0),
        ("positive_limit", 11),
        ("failure_limit", 0),
        ("failure_limit", 11),
        ("minimum_similarity", -1.01),
        ("minimum_similarity", 1.01),
        ("trace_id", "x" * 33),
    ],
)
def test_recommendation_request_rejects_invalid_values(
    field: str,
    value: object,
) -> None:
    data = request_data()
    data[field] = value

    with pytest.raises(ValidationError):
        RecommendationRequest.model_validate(data)


def test_recommendation_request_requires_explicit_query_type() -> None:
    data = request_data()
    del data["query_type"]

    with pytest.raises(ValidationError):
        RecommendationRequest.model_validate(data)


def test_recommendation_request_rejects_duplicate_constraints() -> None:
    data = request_data()
    data["constraints"] = ["Keep face stable", "keep face stable"]

    with pytest.raises(ValidationError):
        RecommendationRequest.model_validate(data)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_recommendation_draft_rejects_out_of_range_provider_confidence(
    confidence: float,
) -> None:
    with pytest.raises(ValidationError):
        RecommendationDraft(
            recommended_prompt="Prompt",
            rationale=["Reason"],
            used_positive_evidence_ids=[],
            failure_warnings=[],
            covered_constraint_ids=[],
            unmet_constraint_ids=[],
            provider_confidence=confidence,
            needs_human_review=False,
        )


def test_recommendation_draft_rejects_invalid_constraint_id_format() -> None:
    with pytest.raises(ValidationError):
        RecommendationDraft(
            recommended_prompt="Prompt",
            rationale=["Reason"],
            used_positive_evidence_ids=[],
            failure_warnings=[],
            covered_constraint_ids=["constraint-1"],
            unmet_constraint_ids=[],
            provider_confidence=0.5,
            needs_human_review=False,
        )


def test_recommendation_draft_rejects_duplicate_warning_evidence() -> None:
    identifier = uuid4()

    with pytest.raises(ValidationError):
        RecommendationDraft(
            recommended_prompt="Prompt",
            rationale=["Reason"],
            used_positive_evidence_ids=[],
            failure_warnings=[
                FailureWarning(evidence_id=identifier, warning="First"),
                FailureWarning(evidence_id=identifier, warning="Second"),
            ],
            covered_constraint_ids=[],
            unmet_constraint_ids=[],
            provider_confidence=0.5,
            needs_human_review=False,
        )
