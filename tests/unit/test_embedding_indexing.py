"""Pure stale-detection behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.db.constants import EMBEDDING_DIMENSIONS
from app.db.models.prompt_example import PromptExample
from app.domain.enums import GenerationStatus, QueryType
from app.embeddings.builder import EmbeddingDocument
from app.embeddings.providers import FakeEmbeddingProvider
from app.services.embedding_indexing import is_embedding_stale


def indexed_example() -> PromptExample:
    """Build one current ORM object without database access."""
    return PromptExample(
        id=uuid4(),
        project_id=uuid4(),
        base_prompt="Prompt",
        expected_result="Expected",
        generation_method="text_to_image",
        target_platform="manual_other",
        query_type=QueryType.OTHER,
        status=GenerationStatus.APPROVED,
        tags=[],
        embedding_text="canonical",
        embedding=[0.0] * EMBEDDING_DIMENSIONS,
        embedding_provider="fake",
        embedding_model="deterministic-token-hash-v1",
        embedding_source_hash="a" * 64,
        embedded_at=datetime.now(UTC),
    )


def test_current_embedding_is_not_stale() -> None:
    assert (
        is_embedding_stale(
            indexed_example(),
            EmbeddingDocument(text="canonical", source_hash="a" * 64),
            FakeEmbeddingProvider(),
        )
        is False
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("embedding", None),
        ("embedding_provider", None),
        ("embedding_provider", "other"),
        ("embedding_model", "other-model"),
        ("embedding_source_hash", "b" * 64),
        ("embedded_at", None),
    ],
)
def test_missing_or_mismatched_metadata_is_stale(field: str, value: object) -> None:
    example = indexed_example()
    setattr(example, field, value)

    assert is_embedding_stale(
        example,
        EmbeddingDocument(text="canonical", source_hash="a" * 64),
        FakeEmbeddingProvider(),
    )


def test_force_marks_current_embedding_stale() -> None:
    assert is_embedding_stale(
        indexed_example(),
        EmbeddingDocument(text="canonical", source_hash="a" * 64),
        FakeEmbeddingProvider(),
        force=True,
    )
