"""Structured local prompt recommendation."""

from app.recommendation.schemas import (
    EvidenceReference,
    PromptRecommendation,
    RecommendationRequest,
    RecommendationResult,
)
from app.recommendation.service import RecommendationService

__all__ = [
    "EvidenceReference",
    "PromptRecommendation",
    "RecommendationRequest",
    "RecommendationResult",
    "RecommendationService",
]
