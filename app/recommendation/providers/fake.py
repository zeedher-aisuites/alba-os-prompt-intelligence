"""Deterministic recommendation provider for tests and local demonstrations."""

from __future__ import annotations

from pydantic import JsonValue

from app.recommendation.protocol import RecommendationDraftValidator
from app.recommendation.schemas import (
    FailureWarning,
    RecommendationContext,
    RecommendationDraft,
)


class FakeRecommendationProvider:
    """Build a useful deterministic draft without a chat model."""

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "deterministic-recommendation-v1"

    @property
    def repair_attempts_used(self) -> int:
        return 0

    async def generate_recommendation(
        self,
        context: RecommendationContext,
        *,
        validate: RecommendationDraftValidator | None = None,
    ) -> RecommendationDraft:
        request = context.request
        prompt_parts = [request.brief]
        if request.constraints:
            prompt_parts.append("Mandatory constraints: " + "; ".join(request.constraints) + ".")
        if request.target_platform is not None:
            prompt_parts.append(f"Target platform: {request.target_platform}.")
        if request.generation_method is not None:
            prompt_parts.append(f"Generation method: {request.generation_method}.")
        if context.positive_evidence:
            prompt_parts.append(
                "Preserve the identity, composition, and continuity requirements "
                "supported by the approved evidence without copying it verbatim."
            )
        if context.failure_evidence:
            prompt_parts.append("Avoid the documented rejected failure patterns.")
        if context.revision_feedback is not None:
            prompt_parts.append("Apply human revision feedback: " + context.revision_feedback + ".")

        rationale = ["The recommendation preserves the explicit brief and mandatory constraints."]
        if context.positive_evidence:
            rationale.append("Approved project evidence supports the proposed direction.")
        else:
            rationale.append("No approved project precedent was available.")
        if context.failure_evidence:
            rationale.append("Rejected evidence was converted into preventive warnings.")
        if context.revision_feedback is not None:
            rationale.append("The single human revision request was incorporated.")

        warnings = [
            FailureWarning(
                evidence_id=item.example_id,
                warning=item.rejection_reason or item.summary,
            )
            for item in context.failure_evidence
        ]
        assumptions = (
            []
            if context.positive_evidence
            else ["No sufficiently similar approved evidence was retrieved."]
        )
        if context.positive_evidence and context.failure_evidence:
            confidence = 0.82
        elif context.positive_evidence:
            confidence = 0.75
        elif context.failure_evidence:
            confidence = 0.35
        else:
            confidence = 0.25

        parameters: dict[str, JsonValue] = {"query_type": request.query_type.value}
        if request.target_platform is not None:
            parameters["target_platform"] = request.target_platform
        if request.generation_method is not None:
            parameters["generation_method"] = request.generation_method

        draft = RecommendationDraft(
            recommended_prompt="\n".join(prompt_parts),
            rationale=rationale,
            used_positive_evidence_ids=[item.example_id for item in context.positive_evidence],
            failure_warnings=warnings,
            covered_constraint_ids=[item.constraint_id for item in context.constraints],
            unmet_constraint_ids=[],
            assumptions=assumptions,
            provider_confidence=confidence,
            needs_human_review=not context.positive_evidence,
            platform_notes=(
                f"Review final formatting for {request.target_platform}."
                if request.target_platform is not None
                else None
            ),
            suggested_parameters=parameters,
            negative_prompt=None,
        )
        if validate is not None:
            validate(draft)
        return draft
