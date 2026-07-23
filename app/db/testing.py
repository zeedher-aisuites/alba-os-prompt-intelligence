"""Safety checks for destructive PostgreSQL integration tests."""

from __future__ import annotations

from typing import cast

from pydantic import PostgresDsn
from sqlalchemy import text

from app.db.session import Database

TEST_DATABASE_NAME = "alba_os_test"
TEST_DATABASE_MARKER = "alba-os-disposable-test-database"


class UnsafeTestDatabaseError(RuntimeError):
    """Raised before a destructive test can target an unapproved database."""


def validate_test_database_url(database_url: PostgresDsn) -> None:
    """Require the explicitly reserved database name without exposing the URL."""
    configured_name = (database_url.path or "").removeprefix("/")
    if configured_name != TEST_DATABASE_NAME:
        raise UnsafeTestDatabaseError(
            f"Destructive tests require database '{TEST_DATABASE_NAME}', "
            f"not '{configured_name or '<missing>'}'."
        )


async def assert_safe_test_database(
    database: Database,
    database_url: PostgresDsn,
) -> None:
    """Verify both configured name and server-side disposable marker."""
    validate_test_database_url(database_url)
    configured_name = database.engine.url.database
    if configured_name != TEST_DATABASE_NAME:
        raise UnsafeTestDatabaseError("The SQLAlchemy engine targets an unsafe database.")

    async with database.engine.connect() as connection:
        result = await connection.execute(
            text(
                """
                SELECT current_database(), shobj_description(oid, 'pg_database')
                FROM pg_database
                WHERE datname = current_database()
                """
            )
        )
        row = result.one()

    current_name = cast(str, row[0])
    marker = cast(str | None, row[1])
    if current_name != TEST_DATABASE_NAME or marker != TEST_DATABASE_MARKER:
        raise UnsafeTestDatabaseError(
            "The connected database is not marked as an Alba disposable test database."
        )
