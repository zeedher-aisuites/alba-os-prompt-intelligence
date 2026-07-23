"""Demo seed, backfill, and evaluation integration tests."""

from __future__ import annotations

import pytest
from app.db.models.prompt_example import PromptExample
from app.db.repositories import ProjectRepository
from app.db.session import Database
from app.domain.enums import GenerationStatus
from app.embeddings.providers import FakeEmbeddingProvider
from app.evaluation.demo_data import DEMO_PROJECT_SLUG
from app.evaluation.runner import RetrievalEvaluationRunner
from app.services.embedding_indexing import EmbeddingIndexingService
from scripts.seed_retrieval_demo import seed_retrieval_demo
from sqlalchemy import func, select


@pytest.mark.postgres
async def test_demo_seed_backfill_and_evaluation_are_reproducible(
    database: Database,
) -> None:
    first = await seed_retrieval_demo(database)
    second = await seed_retrieval_demo(database)

    assert first.projects_created == 1
    assert first.examples_created == 64
    assert second.projects_existing == 1
    assert second.examples_existing == 64
    assert second.projects_created == 0
    assert second.examples_created == 0

    provider = FakeEmbeddingProvider()
    async with database.transaction() as session:
        indexer = EmbeddingIndexingService(session, provider)
        indexed = await indexer.rebuild(project_slug=DEMO_PROJECT_SLUG, batch_size=11)
    assert indexed.selected == 64
    assert indexed.embedded == 64
    assert indexed.batches == 6

    async with database.transaction() as session:
        second_index = await EmbeddingIndexingService(session, provider).rebuild(
            project_slug=DEMO_PROJECT_SLUG
        )
        project = await ProjectRepository(session).get_by_slug(DEMO_PROJECT_SLUG)
        assert project is not None
        status_rows = (
            await session.execute(
                select(PromptExample.status, func.count(PromptExample.id))
                .where(PromptExample.project_id == project.id)
                .group_by(PromptExample.status)
            )
        ).all()
        status_counts = {row[0]: int(row[1]) for row in status_rows}
        report = await RetrievalEvaluationRunner(session, provider).run()

    assert second_index.embedded == 0
    assert second_index.skipped == 64
    assert status_counts == {
        GenerationStatus.APPROVED: 24,
        GenerationStatus.IN_REVIEW: 16,
        GenerationStatus.REJECTED: 24,
    }
    assert report.positive.cases == 10
    assert report.failure.cases == 10
    assert report.overall.cases == 20
    assert report.overall.latency_p95_ms >= report.overall.latency_p50_ms
