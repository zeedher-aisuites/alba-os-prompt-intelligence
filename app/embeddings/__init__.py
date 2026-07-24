"""Embedding construction and provider abstractions."""

from app.embeddings.builder import (
    EmbeddingDocument,
    EmbeddingTextBuilder,
    EmbeddingTextSource,
)
from app.embeddings.protocol import EmbeddingProvider

__all__ = [
    "EmbeddingDocument",
    "EmbeddingProvider",
    "EmbeddingTextBuilder",
    "EmbeddingTextSource",
]
