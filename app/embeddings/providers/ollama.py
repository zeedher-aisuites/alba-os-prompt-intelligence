"""Ollama `/api/embed` adapter."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import httpx

from app.db.constants import EMBEDDING_DIMENSIONS
from app.embeddings.exceptions import (
    EmbeddingProviderUnavailableError,
    MalformedEmbeddingResponseError,
)
from app.embeddings.validation import (
    validate_embedding_batch,
    validate_embedding_inputs,
)


class OllamaEmbeddingProvider:
    """Generate embeddings through an explicitly configured local Ollama API."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model_name: str = "embeddinggemma:300m",
        dimensions: int = EMBEDDING_DIMENSIONS,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._dimensions = dimensions
        self._timeout = httpx.Timeout(timeout_seconds)
        self._client = client

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        validated_texts = validate_embedding_inputs(texts)
        payload = {
            "model": self.model_name,
            "input": validated_texts,
            "truncate": False,
        }
        try:
            if self._client is None:
                async with httpx.AsyncClient(
                    base_url=self._base_url,
                    timeout=self._timeout,
                ) as client:
                    response = await client.post("/api/embed", json=payload)
            else:
                response = await self._client.post("/api/embed", json=payload)
            response.raise_for_status()
        except (httpx.HTTPError, OSError) as exc:
            raise EmbeddingProviderUnavailableError(
                "The Ollama embedding provider is unavailable."
            ) from exc

        try:
            body: object = response.json()
        except ValueError as exc:
            raise MalformedEmbeddingResponseError(
                "The Ollama embedding response is not valid JSON."
            ) from exc
        if not isinstance(body, dict):
            raise MalformedEmbeddingResponseError("The Ollama embedding response is not an object.")
        response_body = cast(dict[str, object], body)
        if response_body.get("model") != self.model_name:
            raise MalformedEmbeddingResponseError(
                "The Ollama response model does not match the configured embedding model."
            )
        if "embeddings" not in response_body:
            raise MalformedEmbeddingResponseError(
                "The Ollama embedding response has no embeddings field."
            )
        return validate_embedding_batch(
            response_body["embeddings"],
            expected_count=len(validated_texts),
            dimensions=self.dimensions,
        )
