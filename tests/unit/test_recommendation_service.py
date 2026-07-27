"""Pure grounding, constraint-accounting, and confidence-policy tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.domain.enums import GenerationStatus, QueryType
from app.recommendation.context import RecommendationContextBuilder
from app.recommendation.exceptions import (
    ConstraintAccountingError,
    EvidenceStatusMismatchError,
    FabricatedConstraintReferenceError,
    FabricatedEvidenceReferenceError,
    MissingPositiveEvidenceCitationError,
)
from app.recommendation.schemas import (
    EvidenceReference,
    FailureWarning,
    RecommendationContext,
    RecommendationDraft,
    RecommendationRequest,
)
from app.recommendation.service import (
    finalize_recommendation,
    validate_draft_grounding,
)


def evidence(
    status: GenerationStatus,
    *,
    similarity: float = 0.8,
) -> EvidenceReference:
    return EvidenceReference(
        example_id=uuid4(),
        status=status,
        query_type=QueryType.AI_INFLUENCER,
        similarity=similarity,
        summary="Evidence summary",
        rejection_reason=("Identity changed." if status is GenerationStatus.REJECTED else None),
    )


def recommendation_context(
    *,
    positive: list[EvidenceReference],
    failures: list[EvidenceReference],
    constraints: list[str] | None = None,
) -> RecommendationContext:
    return RecommendationContextBuilder().build(
        RecommendationRequest(
            project_id=uuid4(),
            brief="Create a portrait.",
            query_type=QueryType.AI_INFLUENCER,
            constraints=constraints or [],
        ),
        positive_evidence=positive,
        failure_evidence=failures,
    )


def draft_for(
    context: RecommendationContext,
    **updates: object,
) -> RecommendationDraft:
    data: dict[str, object] = {
        "recommended_prompt": "Keep the identity stable.",
        "rationale": ["Evidence supports the recommendation."],
        "used_positive_evidence_ids": [item.example_id for item in context.positive_evidence],
        "failure_warnings": [
            FailureWarning(
                evidence_id=item.example_id,
                warning=item.rejection_reason or item.summary,
            )
            for item in context.failure_evidence
        ],
        "covered_constraint_ids": [item.constraint_id for item in context.constraints],
        "unmet_constraint_ids": [],
        "provider_confidence": 0.9,
        "needs_human_review": False,
    }
    data.update(updates)
    return RecommendationDraft.model_validate(data)


def finalize(
    draft: RecommendationDraft,
    context: RecommendationContext,
    *,
    repair_attempts_used: int = 0,
):
    return finalize_recommendation(
        draft,
        context,
        provider_name="fake",
        model_name="fake-v1",
        repair_attempts_used=repair_attempts_used,
    )


def test_valid_grounding_and_constraint_accounting_are_preserved() -> None:
    approved = evidence(GenerationStatus.APPROVED)
    rejected = evidence(GenerationStatus.REJECTED)
    context = recommendation_context(
        positive=[approved],
        failures=[rejected],
        constraints=["Keep the face", "Keep the outfit"],
    )

    result = finalize(draft_for(context), context)

    assert result.used_positive_evidence_ids == [approved.example_id]
    assert result.failure_warnings == [
        FailureWarning(
            evidence_id=rejected.example_id,
            warning="Identity changed.",
        )
    ]
    assert result.covered_constraint_ids == ["C1", "C2"]
    assert result.unmet_constraint_ids == []
    assert result.constraints == context.constraints
    assert result.provider == "fake"
    assert result.model == "fake-v1"
    assert result.confidence < result.provider_confidence


def test_fabricated_positive_evidence_id_is_rejected() -> None:
    approved = evidence(GenerationStatus.APPROVED)
    context = recommendation_context(positive=[approved], failures=[])

    with pytest.raises(FabricatedEvidenceReferenceError):
        finalize(
            draft_for(context, used_positive_evidence_ids=[uuid4()]),
            context,
        )


def test_rejected_id_cannot_be_used_as_positive_evidence() -> None:
    rejected = evidence(GenerationStatus.REJECTED)
    context = recommendation_context(positive=[], failures=[rejected])

    with pytest.raises(EvidenceStatusMismatchError):
        finalize(
            draft_for(
                context,
                used_positive_evidence_ids=[rejected.example_id],
            ),
            context,
        )


def test_warning_must_reference_retrieved_rejected_evidence() -> None:
    approved = evidence(GenerationStatus.APPROVED)
    context = recommendation_context(positive=[approved], failures=[])

    with pytest.raises(EvidenceStatusMismatchError):
        finalize(
            draft_for(
                context,
                failure_warnings=[
                    FailureWarning(
                        evidence_id=approved.example_id,
                        warning="Invalid cross-status warning.",
                    )
                ],
            ),
            context,
        )


def test_warning_with_unknown_evidence_id_is_rejected() -> None:
    context = recommendation_context(positive=[], failures=[])

    with pytest.raises(FabricatedEvidenceReferenceError):
        finalize(
            draft_for(
                context,
                failure_warnings=[
                    FailureWarning(
                        evidence_id=uuid4(),
                        warning="Unknown evidence.",
                    )
                ],
            ),
            context,
        )


def test_missing_positive_citation_is_rejected() -> None:
    approved = evidence(GenerationStatus.APPROVED)
    context = recommendation_context(positive=[approved], failures=[])

    with pytest.raises(MissingPositiveEvidenceCitationError):
        finalize(
            draft_for(context, used_positive_evidence_ids=[]),
            context,
        )


def test_fabricated_constraint_id_is_rejected() -> None:
    context = recommendation_context(
        positive=[],
        failures=[],
        constraints=["Keep the face"],
    )

    with pytest.raises(FabricatedConstraintReferenceError):
        finalize(
            draft_for(context, covered_constraint_ids=["C99"]),
            context,
        )


def test_constraint_cannot_be_covered_and_unmet() -> None:
    context = recommendation_context(
        positive=[],
        failures=[],
        constraints=["Keep the face"],
    )

    with pytest.raises(ConstraintAccountingError):
        finalize(
            draft_for(
                context,
                covered_constraint_ids=["C1"],
                unmet_constraint_ids=["C1"],
            ),
            context,
        )


def test_missing_citation_does_not_mask_invalid_constraint_accounting() -> None:
    approved = evidence(GenerationStatus.APPROVED)
    context = recommendation_context(
        positive=[approved],
        failures=[],
        constraints=["Keep the face"],
    )

    with pytest.raises(ConstraintAccountingError):
        validate_draft_grounding(
            draft_for(
                context,
                used_positive_evidence_ids=[],
                covered_constraint_ids=["C1"],
                unmet_constraint_ids=["C1"],
            ),
            context,
            require_positive_citation=True,
        )


def test_omitted_constraint_is_rejected() -> None:
    context = recommendation_context(
        positive=[],
        failures=[],
        constraints=["Keep the face", "Keep the outfit"],
    )

    with pytest.raises(ConstraintAccountingError):
        finalize(
            draft_for(context, covered_constraint_ids=["C1"]),
            context,
        )


def test_unmet_constraint_forces_review_and_confidence_cap() -> None:
    approved = evidence(GenerationStatus.APPROVED, similarity=0.95)
    context = recommendation_context(
        positive=[approved],
        failures=[],
        constraints=["Keep the face", "Use an editorial composition"],
    )

    result = finalize(
        draft_for(
            context,
            covered_constraint_ids=["C1"],
            unmet_constraint_ids=["C2"],
            provider_confidence=0.99,
        ),
        context,
    )

    assert result.needs_human_review is True
    assert result.confidence <= 0.50
    assert any("Constraint C2 was not covered" in item for item in result.assumptions)


def test_confidence_is_limited_by_positive_similarity() -> None:
    low = evidence(GenerationStatus.APPROVED, similarity=0.2)
    high = evidence(GenerationStatus.APPROVED, similarity=0.9)
    low_context = recommendation_context(positive=[low], failures=[])
    high_context = recommendation_context(positive=[high], failures=[])

    low_result = finalize(draft_for(low_context), low_context)
    high_result = finalize(draft_for(high_context), high_context)

    assert low_result.confidence < high_result.confidence
    assert high_result.confidence < 0.95


def test_structured_repair_applies_confidence_penalty() -> None:
    approved = evidence(GenerationStatus.APPROVED, similarity=0.8)
    context = recommendation_context(positive=[approved], failures=[])

    without_repair = finalize(draft_for(context), context)
    with_repair = finalize(
        draft_for(context),
        context,
        repair_attempts_used=1,
    )

    assert with_repair.confidence == round(without_repair.confidence - 0.10, 4)
    assert with_repair.repair_attempts_used == 1


def test_zero_evidence_is_deterministic() -> None:
    context = recommendation_context(
        positive=[],
        failures=[],
        constraints=["Do not invent precedents"],
    )

    result = finalize(
        draft_for(
            context,
            provider_confidence=0.95,
            needs_human_review=False,
            assumptions=["Approved examples support this result."],
            rationale=["Retrieved precedents support this result."],
        ),
        context,
    )

    assert result.confidence == 0.30
    assert result.needs_human_review is True
    assert result.used_positive_evidence_ids == []
    assert result.failure_warnings == []
    assert result.rationale == [
        (
            "This is a general recommendation based only on the supplied brief "
            "and constraints because no project evidence met the retrieval threshold."
        )
    ]
    assert "No project evidence met the retrieval threshold." in result.assumptions
