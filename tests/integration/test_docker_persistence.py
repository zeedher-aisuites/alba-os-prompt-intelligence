"""Verify PostgreSQL data survives a real Compose container restart."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from pathlib import Path
from uuid import UUID

import pytest
from app.core.config import Settings
from app.db.repositories import ProjectRepository
from app.db.session import Database
from app.domain.schemas import ProjectCreate

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PERSISTENCE_SLUG = "docker-restart-persistence"


def docker_executable() -> str:
    """Resolve Docker explicitly for shells with a stale PATH."""
    configured = os.environ.get("ALBA_DOCKER_EXECUTABLE")
    executable = configured or shutil.which("docker")
    if executable is None:
        pytest.fail("Docker executable is required for the persistence restart test.")
    return executable


def run_docker(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run a scoped Docker command for this repository."""
    return subprocess.run(
        [docker_executable(), *arguments],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )


def build_test_database(settings: Settings) -> Database:
    """Build a resource that can only target the reserved test database."""
    return Database(
        settings,
        database_url=settings.test_database_url.get_secret_value(),
    )


async def create_persistence_record(settings: Settings) -> UUID:
    database = build_test_database(settings)
    try:
        async with database.transaction() as session:
            project = await ProjectRepository(session).create(
                ProjectCreate(
                    name="Docker Restart Persistence",
                    slug=PERSISTENCE_SLUG,
                )
            )
            return project.id
    finally:
        await database.dispose()


async def read_persistence_record(settings: Settings, project_id: UUID) -> bool:
    database = build_test_database(settings)
    try:
        async with database.transaction() as session:
            project = await ProjectRepository(session).get_by_id(project_id)
            return project is not None and project.slug == PERSISTENCE_SLUG
    finally:
        await database.dispose()


async def delete_persistence_record(settings: Settings, project_id: UUID) -> None:
    database = build_test_database(settings)
    try:
        async with database.transaction() as session:
            await ProjectRepository(session).delete(project_id)
    finally:
        await database.dispose()


def wait_for_postgres_health() -> None:
    """Wait until the restarted container reports healthy."""
    for _ in range(30):
        result = run_docker(
            "inspect",
            "--format",
            "{{.State.Health.Status}}",
            "alba-os-postgres-1",
        )
        if result.stdout.strip() == "healthy":
            return
        time.sleep(1)
    pytest.fail("PostgreSQL did not become healthy after Docker restart.")


@pytest.mark.e2e
@pytest.mark.docker
@pytest.mark.postgres
def test_data_persists_after_container_restart(
    migrated_database: None,
    test_settings: Settings,
) -> None:
    project_id = asyncio.run(create_persistence_record(test_settings))
    try:
        run_docker("compose", "restart", "postgres")
        wait_for_postgres_health()
        assert asyncio.run(read_persistence_record(test_settings, project_id)) is True
    finally:
        asyncio.run(delete_persistence_record(test_settings, project_id))
