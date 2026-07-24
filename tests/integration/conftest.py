"""Real PostgreSQL fixtures for Stage 1 integration tests."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncGenerator, Callable, Generator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app.core.config import Settings
from app.db.session import Database
from app.db.testing import assert_safe_test_database
from pydantic import PostgresDsn
from sqlalchemy import text

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def pytest_asyncio_loop_factories(
    config: pytest.Config,
    item: pytest.Item,
) -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
    """Use the selector loop required by Psycopg async on Windows."""
    del config, item
    if sys.platform == "win32":
        return {"selector": asyncio.SelectorEventLoop}
    return {"default": asyncio.new_event_loop}


def alembic_config(database_url: PostgresDsn) -> Config:
    """Create an Alembic configuration rooted at this repository."""
    configuration = Config(str(REPOSITORY_ROOT / "alembic.ini"))
    configuration.set_main_option("script_location", str(REPOSITORY_ROOT / "app/db/migrations"))
    configuration.set_main_option(
        "sqlalchemy.url",
        database_url.unicode_string().replace("%", "%%"),
    )
    return configuration


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Return settings whose destructive target is explicitly separate."""
    return Settings(environment="test")


async def verify_test_database(settings: Settings) -> None:
    """Connect once and verify the server-side safety marker."""
    test_database_url = settings.test_database_url.get_secret_value()
    database = Database(settings, database_url=test_database_url)
    try:
        await assert_safe_test_database(database, test_database_url)
    finally:
        await database.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database(test_settings: Settings) -> Generator[None]:
    """Guard the disposable database before applying any test migration."""
    asyncio.run(verify_test_database(test_settings))
    command.upgrade(
        alembic_config(test_settings.test_database_url.get_secret_value()),
        "head",
    )
    yield


async def truncate_application_tables(database: Database) -> None:
    """Remove test rows while preserving the migrated schema."""
    async with database.engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE TABLE human_reviews, generation_runs, prompt_examples, projects CASCADE")
        )
        checkpoint_table = await connection.scalar(
            text(
                """
                SELECT to_regclass(
                    'alba_workflow_checkpoints.checkpoints'
                )
                """
            )
        )
        if checkpoint_table is not None:
            await connection.execute(
                text(
                    """
                    TRUNCATE TABLE
                        alba_workflow_checkpoints.checkpoint_writes,
                        alba_workflow_checkpoints.checkpoint_blobs,
                        alba_workflow_checkpoints.checkpoints
                    CASCADE
                    """
                )
            )


@pytest_asyncio.fixture
async def database(
    migrated_database: None,
    test_settings: Settings,
) -> AsyncGenerator[Database]:
    """Yield an isolated real database resource for one test."""
    test_database_url = test_settings.test_database_url.get_secret_value()
    database_resource = Database(test_settings, database_url=test_database_url)
    await assert_safe_test_database(database_resource, test_database_url)
    await truncate_application_tables(database_resource)
    try:
        yield database_resource
    finally:
        await truncate_application_tables(database_resource)
        await database_resource.dispose()
