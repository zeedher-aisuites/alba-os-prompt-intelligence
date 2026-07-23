"""Concrete embedding provider adapters."""

from app.embeddings.providers.fake import FakeEmbeddingProvider
from app.embeddings.providers.ollama import OllamaEmbeddingProvider

__all__ = ["FakeEmbeddingProvider", "OllamaEmbeddingProvider"]
