"""Exact pgvector cosine retrieval tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from app.db.constants import EMBEDDING_DIMENSIONS
from app.db.models.prompt_example import PromptExample
from app.db.repositories import ProjectRepository
from app.db.session import Database
from app.domain.enums import GenerationStatus, QueryType
from app.domain.schemas import ProjectCreate, RetrievalQuery
from app.embeddings.providers import FakeEmbeddingProvider
from app.retrieval.service import RetrievalService


def vector(first: float, second: float) -> list[float]:
    """Return a schema-sized test vector."""
    return [first, second, *([0.0] * (EMBEDDING_DIMENSIONS - 2))]


def stored_example(
    *,
    project_id: UUID,
    prompt: str,
    status: GenerationStatus,
    embedding: list[float] | None,
    platform: str = "manual_other",
) -> PromptExample:
    return PromptExample(
        project_id=project_id,
        base_prompt=prompt,
        expected_result="Expected evidence",
        generated_image_description="Observed result",
        generation_method="text_to_image",
        target_platform=platform,
        query_type=QueryType.VIDEO_FRAME,
        status=status,
        quality_score=Decimal("0.800"),
        tags=[prompt],
        embedding_text=prompt,
        embedding=embedding,
        embedding_provider="fake" if embedding is not None else None,
        embedding_model="test-vectors" if embedding is not None else None,
        embedding_source_hash="a" * 64 if embedding is not None else None,
        embedded_at=datetime.now(UTC) if embedding is not None else None,
    )


@pytest.mark.postgres
async def test_exact_retrieval_filters_status_null_vectors_similarity_and_limit(
    database: Database,
) -> None:
    async with database.transaction() as session:
        project = await ProjectRepository(session).create(
            ProjectCreate(name="Retrieval Project", slug="retrieval-project")
        )
        session.add_all(
            [
                stored_example(
                    project_id=project.id,
                    prompt="approved-near",
                    status=GenerationStatus.APPROVED,
                    embedding=vector(1, 0),
                    platform="instagram",
                ),
                stored_example(
                    project_id=project.id,
                    prompt="approved-far",
                    status=GenerationStatus.APPROVED,
                    embedding=vector(0, 1),
                ),
                stored_example(
                    project_id=project.id,
                    prompt="rejected-near",
                    status=GenerationStatus.REJECTED,
                    embedding=vector(1, 0),
                ),
                stored_example(
                    project_id=project.id,
                    prompt="review-near",
                    status=GenerationStatus.IN_REVIEW,
                    embedding=vector(1, 0),
                ),
                stored_example(
                    project_id=project.id,
                    prompt="approved-null",
                    status=GenerationStatus.APPROVED,
                    embedding=None,
                ),
            ]
        )
        await session.flush()
        project_id = project.id

    provider = FakeEmbeddingProvider(
        vectors_by_text={"query": vector(1, 0)},
    )
    async with database.transaction() as session:
        service = RetrievalService(session, provider, maximum_limit=1)
        approved = await service.search_approved_examples(
            RetrievalQuery(
                text="query",
                project_id=project_id,
                query_type=QueryType.VIDEO_FRAME,
                limit=100,
            )
        )
        failures = await service.search_failure_patterns(
            RetrievalQuery(text="query", project_id=project_id, limit=5)
        )

    assert approved.applied_limit == 1
    assert approved.requested_limit == 100
    assert [item.base_prompt for item in approved.items] == ["approved-near"]
    assert abs(approved.items[0].similarity - 1.0) < 1e-6
    assert "embedding" not in approved.items[0].model_dump()
    assert [item.base_prompt for item in failures.items] == ["rejected-near"]
    assert all(item.status == GenerationStatus.APPROVED for item in approved.items)
    assert all(item.status == GenerationStatus.REJECTED for item in failures.items)

    async with database.transaction() as session:
        filtered = await RetrievalService(session, provider).search_approved_examples(
            RetrievalQuery(
                text="query",
                project_id=project_id,
                target_platform="manual_other",
                minimum_similarity=0.5,
                limit=5,
            )
        )

    assert filtered.items == []
    assert filtered.evidence_count == 0
    assert filtered.insufficient_evidence is True
