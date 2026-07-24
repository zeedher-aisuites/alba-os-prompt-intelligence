"""Concrete structured recommendation adapters."""

from app.recommendation.providers.fake import FakeRecommendationProvider
from app.recommendation.providers.ollama import OllamaRecommendationProvider

__all__ = ["FakeRecommendationProvider", "OllamaRecommendationProvider"]
