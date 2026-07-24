"""Project-owned structured recommendation provider contract."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from app.recommendation.schemas import RecommendationContext, RecommendationDraft

RecommendationDraftValidator = Callable[[RecommendationDraft], None]


class RecommendationProvider(Protocol):
    """Generate one validated recommendation draft without persistence access."""

    @property
    def provider_name(self) -> str:
        """Return the provider identifier persisted by the application."""
        ...

    @property
    def model_name(self) -> str:
        """Return the exact configured chat model identifier."""
        ...

    @property
    def repair_attempts_used(self) -> int:
        """Return bounded structured-output repairs used by this provider instance."""
        ...

    async def generate_recommendation(
        self,
        context: RecommendationContext,
        *,
        validate: RecommendationDraftValidator | None = None,
    ) -> RecommendationDraft:
        """Return one Pydantic-validated draft."""
        ...
