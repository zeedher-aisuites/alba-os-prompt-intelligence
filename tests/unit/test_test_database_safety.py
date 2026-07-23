"""Unit tests for destructive-test database guards."""

from __future__ import annotations

import pytest
from app.db.testing import UnsafeTestDatabaseError, validate_test_database_url
from pydantic import PostgresDsn


def test_test_database_guard_accepts_reserved_name() -> None:
    validate_test_database_url(
        PostgresDsn("postgresql+asyncpg://user:password@127.0.0.1/alba_os_test")
    )


@pytest.mark.parametrize("database_name", ["alba_os", "production", "other_test"])
def test_test_database_guard_rejects_every_other_name(database_name: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError):
        validate_test_database_url(
            PostgresDsn(f"postgresql+asyncpg://user:password@127.0.0.1/{database_name}")
        )
