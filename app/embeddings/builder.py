"""Deterministic source text for rebuildable prompt-example embeddings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Final

from app.domain.enums import GenerationStatus, QueryType

SECTION_ORDER: Final[tuple[str, ...]] = (
    "Project",
    "Query type",
    "Expected result",
    "Generated image description",
    "Prompt",
    "Generation method",
    "Target platform",
    "Status",
    "Review notes",
    "Rejection reason",
    "Tags",
)


@dataclass(frozen=True, slots=True)
class EmbeddingTextSource:
    """All source-of-truth fields used to build one embedding document."""

    project: str
    query_type: QueryType
    expected_result: str
    generated_image_description: str | None
    base_prompt: str
    generation_method: str
    target_platform: str
    status: GenerationStatus
    review_notes: str | None
    rejection_reason: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EmbeddingDocument:
    """Canonical embedding text and its UTF-8 SHA-256 digest."""

    text: str
    source_hash: str


def normalize_whitespace(value: str | None) -> str:
    """Collapse all whitespace runs and normalize missing values to empty text."""
    if value is None:
        return ""
    return " ".join(value.split())


def _enum_value(value: Enum) -> str:
    return normalize_whitespace(str(value.value))


class EmbeddingTextBuilder:
    """Build stable text without accessing persistence or an embedding model."""

    def build(self, source: EmbeddingTextSource) -> EmbeddingDocument:
        """Return canonical section text and its SHA-256 source hash."""
        normalized_tags = sorted(
            {normalize_whitespace(tag) for tag in source.tags if normalize_whitespace(tag)},
            key=lambda tag: (tag.casefold(), tag),
        )
        values = (
            normalize_whitespace(source.project),
            _enum_value(source.query_type),
            normalize_whitespace(source.expected_result),
            normalize_whitespace(source.generated_image_description),
            normalize_whitespace(source.base_prompt),
            normalize_whitespace(source.generation_method),
            normalize_whitespace(source.target_platform),
            _enum_value(source.status),
            normalize_whitespace(source.review_notes),
            normalize_whitespace(source.rejection_reason),
            ", ".join(normalized_tags),
        )
        sections = [
            f"{heading}:\n{value}" if value else f"{heading}:"
            for heading, value in zip(SECTION_ORDER, values, strict=True)
        ]
        text = "\n\n".join(sections)
        return EmbeddingDocument(
            text=text,
            source_hash=sha256(text.encode("utf-8")).hexdigest(),
        )
