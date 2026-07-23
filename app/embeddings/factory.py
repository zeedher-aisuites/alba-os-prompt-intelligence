"""Explicit provider construction for command-line application entry points."""

from __future__ import annotations

from typing import Literal

from app.core.config import Settings
from app.embeddings.protocol import EmbeddingProvider
from app.embeddings.providers import FakeEmbeddingProvider, OllamaEmbeddingProvider

EmbeddingProviderKind = Literal["ollama", "fake"]


def create_embedding_provider(
    settings: Settings,
    provider_kind: EmbeddingProviderKind,
) -> EmbeddingProvider:
    """Build one configured provider without service-locator globals."""
    if provider_kind == "fake":
        return FakeEmbeddingProvider()
    return OllamaEmbeddingProvider(
        base_url=settings.ollama_base_url.unicode_string(),
        model_name=settings.embedding_model,
        timeout_seconds=settings.embedding_timeout,
    )
