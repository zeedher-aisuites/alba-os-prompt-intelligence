"""Stage 1 seed integration tests."""

from __future__ import annotations

import pytest
from app.db.repositories import ProjectRepository, PromptExampleRepository
from app.db.session import Database
from app.domain.enums import GenerationStatus
from scripts.seed_database import seed_database


@pytest.mark.postgres
async def test_seed_is_reproducible_and_idempotent(database: Database) -> None:
    first = await seed_database(database)
    second = await seed_database(database)

    assert first.projects_created == 2
    assert first.examples_created == 6
    assert second.projects_existing == 2
    assert second.examples_existing == 6
    assert second.projects_created == 0
    assert second.examples_created == 0

    async with database.transaction() as session:
        project_repository = ProjectRepository(session)
        example_repository = PromptExampleRepository(session)
        projects = await project_repository.list()
        approved = await example_repository.list_by_status(GenerationStatus.APPROVED)
        in_review = await example_repository.list_by_status(GenerationStatus.IN_REVIEW)
        rejected = await example_repository.list_by_status(GenerationStatus.REJECTED)

    assert len(projects) == 2
    assert len(approved) == 2
    assert len(in_review) == 2
    assert len(rejected) == 2
    assert all(example.embedding is None for example in approved + in_review + rejected)
