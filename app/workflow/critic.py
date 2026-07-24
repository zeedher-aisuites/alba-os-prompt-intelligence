"""Deterministic defense-in-depth critic for recommendation workflows."""

from __future__ import annotations

from app.recommendation.exceptions import RecommendationError
from app.recommendation.schemas import PromptRecommendation, RecommendationContext
from app.recommendation.service import validate_draft_grounding
from app.workflow.schemas import CriticRoute, RecommendationCritique

NO_EVIDENCE_CONFIDENCE_MAX = 0.30


class RecommendationCritic:
    """Inspect contracts and grounding without rewriting model output."""

    def critique(
        self,
        recommendation: PromptRecommendation,
        context: RecommendationContext,
    ) -> RecommendationCritique:
        """Return deterministic hard failures, review reasons, and warnings."""
        hard_failures: list[str] = []
        review_reasons: list[str] = []
        warnings: list[str] = []

        try:
            validate_draft_grounding(
                recommendation,
                context,
                require_positive_citation=True,
            )
        except RecommendationError as exc:
            hard_failures.append(f"{exc.error_code}: recommendation grounding is invalid.")

        if not recommendation.recommended_prompt.strip():
            hard_failures.append("The recommended prompt is empty.")
        if set(recommendation.covered_constraint_ids).intersection(
            recommendation.unmet_constraint_ids
        ):
            hard_failures.append("Constraint accounting contains incompatible states.")
        if context.positive_evidence and not recommendation.used_positive_evidence_ids:
            hard_failures.append("Retrieved approved evidence was not cited.")
        if context.failure_evidence and not recommendation.failure_warnings:
            review_reasons.append("Rejected evidence exists without a grounded warning.")
        if recommendation.unmet_constraint_ids:
            review_reasons.append("One or more requested constraints remain unmet.")
        if recommendation.needs_human_review:
            review_reasons.append("The recommendation explicitly requires human review.")
        if not context.positive_evidence:
            review_reasons.append("No approved evidence supports the recommendation.")
            if recommendation.confidence > NO_EVIDENCE_CONFIDENCE_MAX:
                hard_failures.append("Confidence is too high for a no-evidence recommendation.")
        if not context.failure_evidence:
            warnings.append("No rejected failure evidence was available.")
        if not review_reasons and not hard_failures:
            review_reasons.append("Stage 4 requires an explicit terminal human decision.")

        return RecommendationCritique(
            passed=not hard_failures,
            hard_failures=hard_failures,
            review_reasons=review_reasons,
            warnings=warnings,
            recommended_route=(
                CriticRoute.HARD_FAILURE if hard_failures else CriticRoute.HUMAN_REVIEW
            ),
        )
