"""Deterministic local embedding provider for tests and diagnostics."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from hashlib import sha256
from math import sqrt

from app.db.constants import EMBEDDING_DIMENSIONS
from app.embeddings.validation import (
    validate_embedding_batch,
    validate_embedding_inputs,
)

TOKEN_PATTERN = re.compile(r"[\w-]+", flags=re.UNICODE)


class FakeEmbeddingProvider:
    """Generate deterministic token-hash vectors without an external model."""

    def __init__(
        self,
        *,
        dimensions: int = EMBEDDING_DIMENSIONS,
        vectors_by_text: Mapping[str, Sequence[float]] | None = None,
    ) -> None:
        if dimensions < 1:
            raise ValueError("Embedding dimensions must be positive.")
        self._dimensions = dimensions
        self._vectors_by_text = {
            text: list(vector) for text, vector in (vectors_by_text or {}).items()
        }

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "deterministic-token-hash-v1"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        validated_texts = validate_embedding_inputs(texts)
        vectors = [
            self._vectors_by_text.get(text, self._embed_text(text)) for text in validated_texts
        ]
        return validate_embedding_batch(
            vectors,
            expected_count=len(validated_texts),
            dimensions=self.dimensions,
        )

    def _embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = TOKEN_PATTERN.findall(text.casefold())
        for token in tokens:
            digest = sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], byteorder="big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign

        norm = sqrt(sum(value * value for value in vector))
        if norm == 0:
            digest = sha256(text.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], byteorder="big") % self.dimensions] = 1.0
            return vector
        return [value / norm for value in vector]
