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


@pytest.mark.postgres
async def test_embedding_metadata_columns_and_constraints_exist(
    database: Database,
) -> None:
    async with database.engine.connect() as connection:
        columns = (
            await connection.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'prompt_examples'
                    AND column_name IN (
                        'embedding_provider',
                        'embedding_model',
                        'embedding_source_hash',
                        'embedded_at'
                    )
                    ORDER BY column_name
                    """
                )
            )
        ).scalars()
        constraints = (
            await connection.execute(
                text(
                    """
                    SELECT conname, pg_get_constraintdef(oid)
                    FROM pg_constraint
                    WHERE conname IN (
                        'ck_prompt_examples_embedding_source_hash_format',
                        'ck_prompt_examples_embedding_metadata_consistent'
                    )
                    ORDER BY conname
                    """
                )
            )
        ).mappings()

    assert list(columns) == [
        "embedded_at",
        "embedding_model",
        "embedding_provider",
        "embedding_source_hash",
    ]
    definitions = {row["conname"]: row["pg_get_constraintdef"] for row in constraints}
    assert "embedding_source_hash" in definitions["ck_prompt_examples_embedding_source_hash_format"]
    consistency = definitions["ck_prompt_examples_embedding_metadata_consistent"]
    assert "embedding_provider" in consistency
    assert "embedded_at" in consistency


@pytest.mark.postgres
async def test_durable_workflow_schema_and_thread_index_exist(
    database: Database,
) -> None:
    async with database.engine.connect() as connection:
        schema = await connection.scalar(
            text(
                """
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name = 'alba_workflow_checkpoints'
                """
            )
        )
        column = await connection.scalar(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'generation_runs'
                  AND column_name = 'workflow_thread_id'
                """
            )
        )
        index_definition = await connection.scalar(
            text(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND indexname = 'ux_generation_runs_workflow_thread_id'
                """
            )
        )

    assert schema == "alba_workflow_checkpoints"
    assert column == "workflow_thread_id"
    assert index_definition is not None
    assert "UNIQUE INDEX" in index_definition
    assert "workflow_thread_id IS NOT NULL" in index_definition
