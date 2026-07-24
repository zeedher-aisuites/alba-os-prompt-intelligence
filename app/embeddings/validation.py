"""Shared validation for embedding inputs and provider output."""

from __future__ import annotations

from collections.abc import Sequence
from math import isfinite
from typing import cast

from app.embeddings.exceptions import (
    EmbeddingBatchSizeError,
    EmbeddingDimensionError,
    EmptyEmbeddingInputError,
    MalformedEmbeddingResponseError,
    NonFiniteEmbeddingError,
)


def validate_embedding_inputs(texts: Sequence[str]) -> list[str]:
    """Reject empty batches and blank documents while preserving content."""
    if not texts:
        raise EmptyEmbeddingInputError("At least one embedding input is required.")
    validated: list[str] = []
    for index, text in enumerate(texts):
        if not text.strip():
            raise EmptyEmbeddingInputError(f"Embedding input {index} is empty.")
        validated.append(text)
    return validated


def validate_embedding_batch(
    vectors: object,
    *,
    expected_count: int,
    dimensions: int,
) -> list[list[float]]:
    """Validate vector count, shape, numeric values, and finiteness."""
    if not isinstance(vectors, list):
        raise MalformedEmbeddingResponseError("Provider embeddings must be a list.")
    raw_vectors = cast(list[object], vectors)
    if len(raw_vectors) != expected_count:
        raise EmbeddingBatchSizeError(
            f"Expected {expected_count} embeddings, received {len(raw_vectors)}."
        )

    validated: list[list[float]] = []
    for vector_index, raw_vector in enumerate(raw_vectors):
        if not isinstance(raw_vector, list):
            raise MalformedEmbeddingResponseError(f"Embedding {vector_index} must be a list.")
        raw_values = cast(list[object], raw_vector)
        if len(raw_values) != dimensions:
            raise EmbeddingDimensionError(
                f"Embedding {vector_index} has dimension {len(raw_values)}; expected {dimensions}."
            )
        vector: list[float] = []
        for value in raw_values:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise MalformedEmbeddingResponseError(
                    f"Embedding {vector_index} contains a non-numeric value."
                )
            numeric_value = float(value)
            if not isfinite(numeric_value):
                raise NonFiniteEmbeddingError(f"Embedding {vector_index} contains NaN or infinity.")
            vector.append(numeric_value)
        validated.append(vector)
    return validated
