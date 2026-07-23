"""Database readiness endpoint tests."""

from __future__ import annotations

from typing import cast

import pytest
from app.core.config import Settings
from app.db.session import Database
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from pydantic import PostgresDsn, Secret


@pytest.mark.postgres
async def test_database_health_reports_reachable(database: Database) -> None:
    application = create_app(Settings(environment="test"), database)
    transport = ASGITransport(app=application, raise_app_exceptions=False)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/database")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "reachable"}

    document = application.openapi()
    paths = cast(dict[str, object], document["paths"])
    assert "/health/database" in paths


async def test_database_health_returns_typed_unavailable_error() -> None:
    settings = Settings(
        environment="test",
        database_url=Secret(
            PostgresDsn("postgresql+asyncpg://test_user:not-a-real-secret@127.0.0.1:1/alba_os_test")
        ),
        database_pool_timeout=0.1,
    )
    database = Database(settings)
    application = create_app(settings, database)
    transport = ASGITransport(app=application, raise_app_exceptions=False)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health/database")
    finally:
        await database.dispose()

    assert response.status_code == 503
    assert response.json() == {
        "error_code": "DATABASE_UNAVAILABLE",
        "message": "The PostgreSQL persistence service is unavailable.",
        "retryable": True,
        "trace_id": None,
    }
    response_text = response.text.lower()
    assert "postgresql+asyncpg" not in response_text
    assert "127.0.0.1" not in response_text
    assert "test_user" not in response_text
    assert "not-a-real-secret" not in response_text
    assert "traceback" not in response_text
