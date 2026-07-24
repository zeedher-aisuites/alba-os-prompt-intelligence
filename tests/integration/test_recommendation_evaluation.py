"""Deterministic recommendation-evaluation integration test."""

from __future__ import annotations

import pytest
from app.db.repositories import ProjectRepository
from app.db.session import Database
from app.embeddings.providers import FakeEmbeddingProvider
from app.evaluation.demo_data import DEMO_PROJECT_SLUG
from app.recommendation.evaluation import RecommendationEvaluationRunner
from app.recommendation.providers import FakeRecommendationProvider
from app.services.embedding_indexing import EmbeddingIndexingService
from scripts.seed_retrieval_demo import seed_retrieval_demo


@pytest.mark.postgres
async def test_fake_recommendation_evaluation_is_objective_and_persisted(
    database: Database,
) -> None:
    await seed_retrieval_demo(database)
    embedding_provider = FakeEmbeddingProvider()
    async with database.transaction() as session:
        await EmbeddingIndexingService(session, embedding_provider).rebuild(
            project_slug=DEMO_PROJECT_SLUG
        )
        project = await ProjectRepository(session).get_by_slug(DEMO_PROJECT_SLUG)
        assert project is not None
        project_id = project.id

    report = await RecommendationEvaluationRunner(
        database,
        embedding_provider,
        FakeRecommendationProvider(),
    ).run(project_id)

    assert report.metrics.cases == 14
    assert report.metrics.completed_cases == 14
    assert report.metrics.failed_cases == 0
    assert report.metrics.schema_validity_rate == 1
    assert report.metrics.constraint_accounting_rate == 1
    assert report.metrics.covered_constraint_rate == 1
    assert report.metrics.fabricated_constraint_id_rate == 0
    assert report.metrics.unmet_constraint_disclosure_rate == 1
    assert report.metrics.positive_evidence_citation_rate == 1
    assert report.metrics.valid_positive_evidence_rate == 1
    assert report.metrics.valid_failure_warning_citation_rate == 1
    assert report.metrics.fabricated_evidence_rate == 0
    assert report.metrics.no_evidence_handling_rate == 1
    assert report.metrics.successful_run_persistence_rate == 1
    assert report.metrics.repair_attempts_used == 0
    assert 0 <= report.metrics.confidence_min <= report.metrics.confidence_mean
    assert report.metrics.confidence_mean <= report.metrics.confidence_max <= 1
    assert report.metrics.latency_p95_ms >= report.metrics.latency_p50_ms
    assert any(item.contains_injection_attempt for item in report.cases)
