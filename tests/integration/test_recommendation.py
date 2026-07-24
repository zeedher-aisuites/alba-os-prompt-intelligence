"""Structured recommendation integration tests against real PostgreSQL."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from app.db.models.prompt_example import PromptExample
from app.db.repositories import (
    GenerationRunRepository,
    ProjectRepository,
)
from app.db.session import Database
from app.domain.enums import QueryType, RunStatus
from app.domain.exceptions import (
    ConstraintViolationError,
    InvalidRunTransitionError,
)
from app.domain.schemas import (
    GenerationRunComplete,
    GenerationRunCreate,
    GenerationRunFail,
    ProjectCreate,
)
from app.embeddings.providers import FakeEmbeddingProvider
from app.evaluation.demo_data import DEMO_PROJECT_SLUG
from app.recommendation.exceptions import FabricatedEvidenceReferenceError
from app.recommendation.protocol import RecommendationDraftValidator
from app.recommendation.providers import FakeRecommendationProvider
from app.recommendation.schemas import (
    RecommendationContext,
    RecommendationDraft,
    RecommendationRequest,
)
from app.recommendation.service import RecommendationService
from app.services.embedding_indexing import EmbeddingIndexingService
from scripts.seed_retrieval_demo import seed_retrieval_demo
from sqlalchemy import func, select


class CountingEmbeddingProvider(FakeEmbeddingProvider):
    """Count query embeddings while retaining deterministic fake vectors."""

    def __init__(self) -> None:
        super().__init__()
        self.query_calls = 0

    async def embed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        return await super().embed_query(text)


class FabricatingRecommendationProvider:
    """Return one schema-valid but unavailable evidence reference."""

    @property
    def provider_name(self) -> str:
        return "fabricating-test"

    @property
    def model_name(self) -> str:
        return "fabricating-v1"

    @property
    def repair_attempts_used(self) -> int:
        return 0

    async def generate_recommendation(
        self,
        context: RecommendationContext,
        *,
        validate: RecommendationDraftValidator | None = None,
    ) -> RecommendationDraft:
        draft = RecommendationDraft(
            recommended_prompt="A structurally valid but ungrounded prompt.",
            rationale=["This reference is intentionally invalid."],
            used_positive_evidence_ids=[uuid4()],
            failure_warnings=[],
            covered_constraint_ids=[item.constraint_id for item in context.constraints],
            unmet_constraint_ids=[],
            provider_confidence=0.9,
            needs_human_review=False,
        )
        if validate is not None:
            validate(draft)
        return draft


async def indexed_demo_project(database: Database) -> UUID:
    """Seed and fake-index the deterministic retrieval project."""
    await seed_retrieval_demo(database)
    async with database.transaction() as session:
        report = await EmbeddingIndexingService(
            session,
            FakeEmbeddingProvider(),
        ).rebuild(project_slug=DEMO_PROJECT_SLUG)
        project = await ProjectRepository(session).get_by_slug(DEMO_PROJECT_SLUG)
        assert project is not None
        assert report.embedded == 64
        return project.id


def recommendation_request(project_id: UUID) -> RecommendationRequest:
    return RecommendationRequest(
        project_id=project_id,
        brief="Create the same cobalt virtual host in a new lounge portrait.",
        query_type=QueryType.AI_INFLUENCER,
        constraints=["Preserve the same face", "Keep the approved outfit"],
        positive_limit=3,
        failure_limit=3,
        trace_id="stage3-integration",
    )


@pytest.mark.postgres
async def test_recommendation_reuses_one_embedding_and_persists_completed_run(
    database: Database,
) -> None:
    project_id = await indexed_demo_project(database)
    embedding_provider = CountingEmbeddingProvider()
    result = await RecommendationService(
        database,
        embedding_provider,
        FakeRecommendationProvider(),
    ).recommend(recommendation_request(project_id))

    assert embedding_provider.query_calls == 1
    assert result.status is RunStatus.COMPLETED
    assert len(result.positive_evidence) == 3
    assert len(result.failure_evidence) == 3
    assert result.recommendation.failure_warnings
    assert result.recommendation.used_positive_evidence_ids
    assert result.recommendation.covered_constraint_ids == ["C1", "C2"]
    assert result.recommendation.unmet_constraint_ids == []
    assert result.recommendation.confidence < result.recommendation.provider_confidence
    assert "Preserve the same face" in result.recommendation.recommended_prompt
    assert result.recommendation.provider == "fake"
    assert result.recommendation.model == "deterministic-recommendation-v1"

    async with database.transaction() as session:
        repository = GenerationRunRepository(session)
        stored = await repository.get_by_id(result.run_id)
        read_again = await repository.get_by_id(result.run_id)
        vector_count = await session.scalar(
            select(func.count(PromptExample.id)).where(PromptExample.embedding.is_not(None))
        )

    assert stored is not None
    assert read_again is not None
    assert stored.id == read_again.id
    assert stored.status is RunStatus.COMPLETED
    assert stored.provider == "fake"
    assert stored.model == "deterministic-recommendation-v1"
    assert stored.trace_id == "stage3-integration"
    assert stored.completed_at is not None
    assert stored.completed_at.utcoffset() is not None
    assert vector_count == 64
    serialized = json.dumps(
        {
            "recommendation": stored.prompt_recommendation,
            "parameters": stored.provider_parameters,
        }
    )
    assert "query_vector" not in serialized
    assert '"embedding":' not in serialized


@pytest.mark.postgres
async def test_zero_evidence_returns_limited_reviewable_recommendation(
    database: Database,
) -> None:
    async with database.transaction() as session:
        project = await ProjectRepository(session).create(
            ProjectCreate(name="Empty Evidence Project", slug="empty-evidence")
        )
        project_id = project.id

    result = await RecommendationService(
        database,
        FakeEmbeddingProvider(),
        FakeRecommendationProvider(),
    ).recommend(
        RecommendationRequest(
            project_id=project_id,
            brief="Create a new experimental portrait.",
            query_type=QueryType.AI_INFLUENCER,
        )
    )

    assert result.positive_evidence == []
    assert result.failure_evidence == []
    assert result.recommendation.needs_human_review is True
    assert result.recommendation.confidence <= 0.30
    assert result.recommendation.used_positive_evidence_ids == []
    assert result.recommendation.failure_warnings == []
    assert any("No project evidence" in item for item in result.recommendation.assumptions)


@pytest.mark.postgres
async def test_fabricated_evidence_marks_run_failed(database: Database) -> None:
    project_id = await indexed_demo_project(database)

    with pytest.raises(FabricatedEvidenceReferenceError):
        await RecommendationService(
            database,
            FakeEmbeddingProvider(),
            FabricatingRecommendationProvider(),
        ).recommend(recommendation_request(project_id))

    async with database.transaction() as session:
        runs = await GenerationRunRepository(session).list_by_project(project_id)

    assert len(runs) == 1
    assert runs[0].status is RunStatus.FAILED
    assert runs[0].error_code == "FABRICATED_EVIDENCE_REFERENCE"
    assert runs[0].prompt_recommendation == {}
    assert runs[0].completed_at is not None


@pytest.mark.postgres
async def test_generation_run_repository_transitions_and_project_isolation(
    database: Database,
) -> None:
    async with database.transaction() as session:
        projects = ProjectRepository(session)
        first_project = await projects.create(
            ProjectCreate(name="First Run Project", slug="first-runs")
        )
        second_project = await projects.create(
            ProjectCreate(name="Second Run Project", slug="second-runs")
        )
        repository = GenerationRunRepository(session)
        first = await repository.create(
            GenerationRunCreate(
                project_id=first_project.id,
                brief_text="First brief",
                prompt_recommendation={},
                provider="fake",
                model="fake-v1",
                generation_method="text_to_image",
                status=RunStatus.PENDING,
            )
        )
        second = await repository.create(
            GenerationRunCreate(
                project_id=second_project.id,
                brief_text="Second brief",
                prompt_recommendation={},
                provider="fake",
                model="fake-v1",
                generation_method="text_to_image",
                status=RunStatus.RUNNING,
            )
        )
        first_id = first.id
        second_id = second.id
        first_project_id = first_project.id
        second_project_id = second_project.id

    async with database.transaction() as session:
        repository = GenerationRunRepository(session)
        await repository.mark_running(first_id)
        completed = await repository.mark_completed(
            first_id,
            GenerationRunComplete(
                prompt_recommendation={"recommended_prompt": "Completed"},
                provider_parameters={"source": "test"},
                latency_ms=10,
            ),
        )
        failed = await repository.mark_failed(
            second_id,
            GenerationRunFail(error_code="PROVIDER_FAILED", latency_ms=20),
        )

    assert completed.status is RunStatus.COMPLETED
    assert failed.status is RunStatus.FAILED

    with pytest.raises(InvalidRunTransitionError):
        async with database.transaction() as session:
            await GenerationRunRepository(session).mark_failed(
                first_id,
                GenerationRunFail(error_code="TOO_LATE", latency_ms=30),
            )

    async with database.transaction() as session:
        repository = GenerationRunRepository(session)
        first_runs = await repository.list_by_project(first_project_id)
        second_runs = await repository.list_by_project(second_project_id)

    assert [run.id for run in first_runs] == [first_id]
    assert [run.id for run in second_runs] == [second_id]


@pytest.mark.postgres
async def test_concurrent_terminal_transitions_allow_only_one_winner(
    database: Database,
) -> None:
    async with database.transaction() as session:
        project = await ProjectRepository(session).create(
            ProjectCreate(name="Concurrent Run Project", slug="concurrent-runs")
        )
        run = await GenerationRunRepository(session).create(
            GenerationRunCreate(
                project_id=project.id,
                brief_text="Run with competing terminal transitions.",
                prompt_recommendation={},
                provider="fake",
                model="fake-v1",
                generation_method="text_to_image",
                status=RunStatus.RUNNING,
            )
        )
        run_id = run.id

    async def complete() -> object:
        async with database.transaction() as session:
            return await GenerationRunRepository(session).mark_completed(
                run_id,
                GenerationRunComplete(
                    prompt_recommendation={"recommended_prompt": "Completed"},
                    provider_parameters={"source": "concurrency-test"},
                    latency_ms=10,
                ),
            )

    async def fail() -> object:
        async with database.transaction() as session:
            return await GenerationRunRepository(session).mark_failed(
                run_id,
                GenerationRunFail(error_code="COMPETING_FAILURE", latency_ms=20),
            )

    outcomes = await asyncio.gather(complete(), fail(), return_exceptions=True)

    assert sum(isinstance(item, InvalidRunTransitionError) for item in outcomes) == 1
    assert sum(not isinstance(item, BaseException) for item in outcomes) == 1
    async with database.transaction() as session:
        stored = await GenerationRunRepository(session).get_by_id(run_id)

    assert stored is not None
    assert stored.status in {RunStatus.COMPLETED, RunStatus.FAILED}


@pytest.mark.postgres
async def test_failed_final_write_rolls_back_completion(database: Database) -> None:
    async with database.transaction() as session:
        project = await ProjectRepository(session).create(
            ProjectCreate(name="Rollback Run Project", slug="rollback-runs")
        )
        run = await GenerationRunRepository(session).create(
            GenerationRunCreate(
                project_id=project.id,
                brief_text="Run that must remain running after rollback.",
                prompt_recommendation={},
                provider="fake",
                model="fake-v1",
                generation_method="text_to_image",
                status=RunStatus.RUNNING,
            )
        )
        run_id = run.id

    invalid = GenerationRunComplete.model_construct(
        prompt_recommendation={"recommended_prompt": "Invalid latency"},
        provider_parameters={},
        latency_ms=-1,
    )
    with pytest.raises(ConstraintViolationError):
        async with database.transaction() as session:
            await GenerationRunRepository(session).mark_completed(run_id, invalid)

    async with database.transaction() as session:
        stored = await GenerationRunRepository(session).get_by_id(run_id)

    assert stored is not None
    assert stored.status is RunStatus.RUNNING
    assert stored.prompt_recommendation == {}
    assert stored.completed_at is None
