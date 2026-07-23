"""Repository and relational-integrity tests using PostgreSQL."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from app.db.models.generation_run import GenerationRun
from app.db.models.human_review import HumanReview
from app.db.models.prompt_example import PromptExample
from app.db.repositories import ProjectRepository, PromptExampleRepository
from app.db.session import Database
from app.domain.enums import GenerationStatus, QueryType, RunStatus
from app.domain.exceptions import (
    DuplicateSlugError,
    EntityNotFoundError,
    ResourceInUseError,
)
from app.domain.schemas import (
    ProjectCreate,
    ProjectUpdate,
    PromptExampleCreate,
    PromptExampleUpdate,
)
from sqlalchemy import select
from sqlalchemy.orm import selectinload


def project_input(*, slug: str = "test-project") -> ProjectCreate:
    """Build valid project input."""
    return ProjectCreate(name="Test Project", slug=slug, description="Integration fixture")


def example_input(project_id: UUID) -> PromptExampleCreate:
    """Build valid prompt-example input."""
    return PromptExampleCreate(
        project_id=project_id,
        base_prompt="Cobalt host enters the lounge from left to right.",
        expected_result="Stable wardrobe and direction.",
        generated_image_description="Host and guest enter coherently.",
        generation_method="text_to_image",
        target_platform="manual_other",
        query_type=QueryType.VIDEO_FRAME,
        status=GenerationStatus.APPROVED,
        quality_score=Decimal("0.900"),
        tags=["continuity", "cobalt"],
        embedding_text="Project: Test\nPrompt: Cobalt host enters.",
    )


@pytest.mark.postgres
async def test_project_crud(database: Database) -> None:
    async with database.transaction() as session:
        repository = ProjectRepository(session)
        created = await repository.create(project_input())
        project_id = created.id
        original_updated_at = created.updated_at
        assert created.created_at.utcoffset() == timedelta(0)
        assert created.updated_at.utcoffset() == timedelta(0)

    async with database.transaction() as session:
        repository = ProjectRepository(session)
        loaded = await repository.get_by_id(project_id)
        by_slug = await repository.get_by_slug("test-project")
        listed = await repository.list()
        updated = await repository.update(
            project_id,
            ProjectUpdate(name="Updated Project"),
        )

        assert loaded is not None
        assert loaded.id == project_id
        assert by_slug is not None
        assert by_slug.id == project_id
        assert [project.id for project in listed] == [project_id]
        assert updated.name == "Updated Project"
        assert updated.updated_at >= original_updated_at

    async with database.transaction() as session:
        repository = ProjectRepository(session)
        await repository.delete(project_id)
        assert await repository.get_by_id(project_id) is None


@pytest.mark.postgres
async def test_missing_project_raises_typed_error(database: Database) -> None:
    missing_id = uuid4()
    with pytest.raises(EntityNotFoundError):
        async with database.transaction() as session:
            await ProjectRepository(session).update(
                missing_id,
                ProjectUpdate(name="Missing"),
            )


@pytest.mark.postgres
async def test_duplicate_slug_rolls_back_failed_transaction(database: Database) -> None:
    async with database.transaction() as session:
        await ProjectRepository(session).create(project_input(slug="unique"))

    with pytest.raises(DuplicateSlugError):
        async with database.transaction() as session:
            await ProjectRepository(session).create(project_input(slug="unique"))

    async with database.transaction() as session:
        projects = await ProjectRepository(session).list()
        assert [project.slug for project in projects] == ["unique"]


@pytest.mark.postgres
async def test_exception_rolls_back_unit_of_work(database: Database) -> None:
    class ForcedRollbackError(RuntimeError):
        pass

    with pytest.raises(ForcedRollbackError):
        async with database.transaction() as session:
            project = await ProjectRepository(session).create(project_input())
            await PromptExampleRepository(session).create(example_input(project.id))
            raise ForcedRollbackError

    async with database.transaction() as session:
        assert await ProjectRepository(session).list() == []
        assert list((await session.scalars(select(PromptExample))).all()) == []


@pytest.mark.postgres
async def test_prompt_example_relations_and_review_cascade(database: Database) -> None:
    async with database.transaction() as session:
        project = await ProjectRepository(session).create(project_input())
        example = await PromptExampleRepository(session).create(example_input(project.id))
        session.add(
            HumanReview(
                prompt_example_id=example.id,
                overall_score=Decimal("0.800"),
                prompt_adherence_score=Decimal("0.900"),
                identity_consistency_score=Decimal("0.800"),
                outfit_fidelity_score=Decimal("0.900"),
                composition_score=Decimal("0.700"),
                physical_coherence_score=Decimal("0.800"),
                continuity_score=Decimal("0.850"),
                strengths=["Wardrobe continuity"],
                problems=[],
                recommendations=["Preserve screen direction"],
                final_status=GenerationStatus.APPROVED,
            )
        )
        await session.flush()
        example_id = example.id

    async with database.transaction() as session:
        statement = (
            select(PromptExample)
            .options(
                selectinload(PromptExample.project),
                selectinload(PromptExample.human_reviews),
            )
            .where(PromptExample.id == example_id)
        )
        loaded = await session.scalar(statement)

        assert loaded is not None
        assert loaded.project.slug == "test-project"
        assert len(loaded.human_reviews) == 1
        assert loaded.embedding is None

    async with database.transaction() as session:
        updated = await PromptExampleRepository(session).update(
            example_id,
            PromptExampleUpdate(review_notes="Updated after relational review."),
        )
        assert updated.review_notes == "Updated after relational review."

    async with database.transaction() as session:
        await PromptExampleRepository(session).delete(example_id)

    async with database.transaction() as session:
        reviews = list((await session.scalars(select(HumanReview))).all())
        assert reviews == []


@pytest.mark.postgres
async def test_project_delete_is_restricted_when_runs_exist(database: Database) -> None:
    async with database.transaction() as session:
        project = await ProjectRepository(session).create(project_input())
        session.add(
            GenerationRun(
                project_id=project.id,
                brief_text="Persist this placeholder run.",
                prompt_recommendation={"prompt": "A prompt"},
                provider="mock",
                model="mock-v1",
                generation_method="text_to_image",
                provider_parameters={},
                status=RunStatus.PENDING,
            )
        )
        await session.flush()
        project_id = project.id

    with pytest.raises(ResourceInUseError):
        async with database.transaction() as session:
            await ProjectRepository(session).delete(project_id)
