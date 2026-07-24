"""Explicit recommendation provider construction."""

from __future__ import annotations

from typing import Literal

from app.core.config import Settings
from app.recommendation.protocol import RecommendationProvider
from app.recommendation.providers import (
    FakeRecommendationProvider,
    OllamaRecommendationProvider,
)

RecommendationProviderKind = Literal["fake", "ollama"]


def create_recommendation_provider(
    settings: Settings,
    provider_kind: RecommendationProviderKind,
) -> RecommendationProvider:
    """Create one configured provider without fallbacks or downloads."""
    if provider_kind == "fake":
        return FakeRecommendationProvider()
    return OllamaRecommendationProvider(
        base_url=settings.ollama_base_url.unicode_string(),
        model_name=settings.recommendation_model,
        timeout_seconds=settings.recommendation_timeout,
        maximum_output_tokens=settings.recommendation_max_output_tokens,
        maximum_repair_attempts=settings.recommendation_max_repair_attempts,
    )
