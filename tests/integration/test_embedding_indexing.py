"""Embedding persistence, idempotence, and hash-regeneration tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from app.db.constants import EMBEDDING_DIMENSIONS
from app.db.repositories import ProjectRepository, PromptExampleRepository
from app.db.session import Database
from app.domain.enums import GenerationStatus, QueryType
from app.domain.schemas import ProjectCreate, PromptExampleCreate, PromptExampleUpdate
from app.embeddings.exceptions import EmbeddingProviderUnavailableError
from app.embeddings.providers import FakeEmbeddingProvider
from app.services.embedding_indexing import EmbeddingIndexingService
from sqlalchemy.exc import IntegrityError


async def create_example(database: Database) -> tuple[str, UUID]:
    """Create one unindexed example and return project slug plus example id."""
    async with database.transaction() as session:
        project = await ProjectRepository(session).create(
            ProjectCreate(name="Indexing Project", slug="indexing-project")
        )
        example = await PromptExampleRepository(session).create(
            PromptExampleCreate(
                project_id=project.id,
                base_prompt="Cobalt host enters from left to right.",
                expected_result="Stable wardrobe and direction.",
                generated_image_description="A coherent entrance.",
                generation_method="text_to_image",
                target_platform="manual_other",
                query_type=QueryType.VIDEO_FRAME,
                status=GenerationStatus.APPROVED,
                quality_score=Decimal("0.900"),
                tags=["cobalt", "continuity"],
                embedding_text="legacy non-canonical text",
            )
        )
        return project.slug, example.id


@pytest.mark.postgres
async def test_indexing_persists_vector_metadata_and_is_idempotent(
    database: Database,
) -> None:
    project_slug, example_id = await create_example(database)
    provider = FakeEmbeddingProvider()

    async with database.transaction() as session:
        first = await EmbeddingIndexingService(session, provider).rebuild(
            project_slug=project_slug,
            batch_size=1,
        )

    assert first.selected == 1
    assert first.stale == 1
    assert first.embedded == 1
    assert first.batches == 1

    async with database.transaction() as session:
        loaded = await PromptExampleRepository(session).get_by_id(example_id)
        assert loaded is not None
        assert loaded.embedding is not None
        assert len(loaded.embedding) == EMBEDDING_DIMENSIONS
        assert loaded.embedding_provider == "fake"
        assert loaded.embedding_model == "deterministic-token-hash-v1"
        assert loaded.embedding_source_hash is not None
        assert len(loaded.embedding_source_hash) == 64
        assert loaded.embedded_at is not None
        assert loaded.embedded_at.utcoffset() == timedelta(0)
        original_hash = loaded.embedding_source_hash

    async with database.transaction() as session:
        second = await EmbeddingIndexingService(session, provider).rebuild(
            project_slug=project_slug
        )

    assert second.selected == 1
    assert second.stale == 0
    assert second.embedded == 0
    assert second.skipped == 1
    assert second.batches == 0

    async with database.transaction() as session:
        await PromptExampleRepository(session).update(
            example_id,
            PromptExampleUpdate(base_prompt="Amber host exits toward the camera."),
        )

    async with database.transaction() as session:
        regenerated = await EmbeddingIndexingService(session, provider).rebuild(
            project_slug=project_slug
        )
    assert regenerated.embedded == 1

    async with database.transaction() as session:
        changed = await PromptExampleRepository(session).get_by_id(example_id)
        assert changed is not None
        assert changed.embedding_source_hash != original_hash


@pytest.mark.postgres
async def test_dry_run_reports_without_persisting(database: Database) -> None:
    project_slug, example_id = await create_example(database)

    async with database.transaction() as session:
        report = await EmbeddingIndexingService(
            session,
            FakeEmbeddingProvider(),
        ).rebuild(project_slug=project_slug, dry_run=True)

    assert report.stale == 1
    assert report.would_embed == 1
    assert report.embedded == 0
    assert report.batches == 0

    async with database.transaction() as session:
        example = await PromptExampleRepository(session).get_by_id(example_id)
        assert example is not None
        assert example.embedding is None
        assert example.embedding_provider is None


class FailingSecondBatchProvider(FakeEmbeddingProvider):
    """Allow one batch and fail the next to exercise transaction rollback."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        if self.calls == 2:
            raise EmbeddingProviderUnavailableError("Forced provider failure.")
        return await super().embed_documents(texts)


@pytest.mark.postgres
async def test_provider_failure_rolls_back_previous_embedding_batch(
    database: Database,
) -> None:
    async with database.transaction() as session:
        project = await ProjectRepository(session).create(
            ProjectCreate(name="Rollback Indexing", slug="rollback-indexing")
        )
        repository = PromptExampleRepository(session)
        example_ids: list[UUID] = []
        for number in range(2):
            example = await repository.create(
                PromptExampleCreate(
                    project_id=project.id,
                    base_prompt=f"Rollback prompt {number}",
                    expected_result="No partial vectors.",
                    generation_method="text_to_image",
                    target_platform="manual_other",
                    query_type=QueryType.OTHER,
                    embedding_text=f"legacy {number}",
                )
            )
            example_ids.append(example.id)

    provider = FailingSecondBatchProvider()
    with pytest.raises(EmbeddingProviderUnavailableError):
        async with database.transaction() as session:
            await EmbeddingIndexingService(session, provider).rebuild(
                project_slug="rollback-indexing",
                batch_size=1,
            )

    async with database.transaction() as session:
        repository = PromptExampleRepository(session)
        loaded = [await repository.get_by_id(identifier) for identifier in example_ids]

    assert all(example is not None and example.embedding is None for example in loaded)


@pytest.mark.postgres
async def test_embedding_metadata_constraint_rejects_partial_state(
    database: Database,
) -> None:
    _, example_id = await create_example(database)

    with pytest.raises(IntegrityError):
        async with database.transaction() as session:
            example = await PromptExampleRepository(session).get_by_id(example_id)
            assert example is not None
            example.embedding_provider = "ollama"
            await session.flush()

    async with database.transaction() as session:
        example = await PromptExampleRepository(session).get_by_id(example_id)

    assert example is not None
    assert example.embedding is None
    assert example.embedding_provider is None
