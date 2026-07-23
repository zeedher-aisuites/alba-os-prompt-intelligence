"""HTTP smoke tests for the FastAPI bootstrap."""

from __future__ import annotations

from app.core.config import Settings
from app.main import create_app
from httpx import ASGITransport, AsyncClient


async def test_service_info_exposes_name_and_version() -> None:
    settings = Settings(app_name="Test Alba", environment="test")
    transport = ASGITransport(app=create_app(settings))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "name": "Test Alba",
        "version": "0.1.0",
        "docs_url": "/docs",
    }


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
