"""Opt-in integration check for the real local EmbeddingGemma model."""

from __future__ import annotations

import pytest
from app.core.config import Settings
from app.db.constants import EMBEDDING_DIMENSIONS
from app.embeddings.exceptions import EmbeddingProviderUnavailableError
from app.embeddings.providers import OllamaEmbeddingProvider


@pytest.mark.ollama
async def test_embeddinggemma_returns_real_768_dimension_vector(
    test_settings: Settings,
) -> None:
    provider = OllamaEmbeddingProvider(
        base_url=test_settings.ollama_base_url.unicode_string(),
        model_name=test_settings.embedding_model,
        timeout_seconds=test_settings.embedding_timeout,
    )
    try:
        vector = await provider.embed_query("A cobalt-dressed virtual host in a premium lounge.")
    except EmbeddingProviderUnavailableError:
        pytest.skip(
            "Ollama or the pre-pulled embeddinggemma:300m model is unavailable; "
            "install Ollama and run `ollama pull embeddinggemma:300m`."
        )

    assert provider.provider_name == "ollama"
    assert provider.model_name == "embeddinggemma:300m"
    assert len(vector) == EMBEDDING_DIMENSIONS
