"""HTTP smoke tests for the FastAPI bootstrap."""

from __future__ import annotations

import pytest
from app.core.config import Settings
from app.db.session import Database
from app.main import create_app
from httpx import ASGITransport, AsyncClient


@pytest.mark.postgres
async def test_dashboard_is_server_rendered_and_service_info_remains_versioned(
    database: Database,
) -> None:
    settings = Settings(app_name="Test Alba", environment="test")
    transport = ASGITransport(app=create_app(settings, database))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        dashboard = await client.get("/")
        response = await client.get("/api")

    assert response.status_code == 200
    assert response.json() == {
        "name": "Test Alba",
        "version": "0.1.0",
        "docs_url": "/docs",
    }
    assert dashboard.status_code == 200
    assert dashboard.headers["content-type"].startswith("text/html")
    assert "Alba OS Prompt Intelligence" in dashboard.text
    assert dashboard.headers["x-content-type-options"] == "nosniff"


async def test_health_reports_process_status() -> None:
    settings = Settings(app_name="Test Alba", environment="test")
    transport = ASGITransport(app=create_app(settings))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Test Alba",
        "environment": "test",
    }
