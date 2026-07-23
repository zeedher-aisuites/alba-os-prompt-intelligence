"""Alembic integration tests against the real PostgreSQL service."""

from __future__ import annotations

import asyncio

import pytest
from alembic import command
from app.core.config import Settings
from app.db.session import Database
from sqlalchemy import text

from tests.integration.conftest import alembic_config


async def vector_extension_exists(settings: Settings) -> bool:
    """Check extension state without depending on application tables."""
    database = Database(
        settings,
        database_url=settings.test_database_url.get_secret_value(),
    )
    try:
        async with database.engine.connect() as connection:
            extension = await connection.scalar(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            )
        return extension == "vector"
    finally:
        await database.dispose()


@pytest.mark.postgres
def test_migration_round_trip_from_empty(
    migrated_database: None,
    test_settings: Settings,
) -> None:
    configuration = alembic_config(test_settings.test_database_url.get_secret_value())

    command.downgrade(configuration, "base")
    assert asyncio.run(vector_extension_exists(test_settings)) is True
    command.upgrade(configuration, "head")


@pytest.mark.postgres
async def test_pgvector_extension_is_enabled(database: Database) -> None:
    async with database.engine.connect() as connection:
        extension = await connection.scalar(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )

    assert extension == "vector"
