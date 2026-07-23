"""Project-owned embedding provider contract."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class EmbeddingProvider(Protocol):
    """Adapter boundary for query and document embeddings."""

    @property
    def provider_name(self) -> str:
        """Return a stable provider identifier."""
        ...

    @property
    def model_name(self) -> str:
        """Return the exact model identifier."""
        ...

    @property
    def dimensions(self) -> int:
        """Return the required output-vector dimension."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Embed one retrieval query."""
        ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a non-empty document batch without reordering it."""
        ...
