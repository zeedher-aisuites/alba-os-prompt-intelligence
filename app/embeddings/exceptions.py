"""Typed embedding-provider and validation failures."""

from __future__ import annotations


class EmbeddingError(Exception):
    """Base class for expected embedding failures."""


class EmptyEmbeddingInputError(EmbeddingError):
    """Raised when a batch or one of its documents is empty."""


class EmbeddingProviderUnavailableError(EmbeddingError):
    """Raised when the configured provider cannot answer."""


class MalformedEmbeddingResponseError(EmbeddingError):
    """Raised when a provider returns an unexpected response shape."""


class EmbeddingBatchSizeError(MalformedEmbeddingResponseError):
    """Raised when a provider returns a different vector count."""


class EmbeddingDimensionError(MalformedEmbeddingResponseError):
    """Raised when a vector does not match the configured dimension."""


class NonFiniteEmbeddingError(MalformedEmbeddingResponseError):
    """Raised when a vector contains NaN or infinity."""
