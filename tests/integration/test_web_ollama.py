"""Opt-in real Ollama coverage for the versioned local workflow HTTP API."""

from __future__ import annotations

from typing import cast
from uuid import uuid4

import httpx
import pytest
from app.core.config import Settings
from app.db.repositories import ProjectRepository
from app.db.session import Database
from app.domain.enums import QueryType
from app.domain.schemas import ProjectCreate
from app.main import create_app
from app.workflow.checkpoint import open_workflow_checkpointer, setup_workflow_checkpointer
from httpx import ASGITransport, AsyncClient
from pydantic import Secret


async def installed_models(settings: Settings) -> set[str]:
    """Read preinstalled local model names without pulling or mutating Ollama."""
    try:
        async with httpx.AsyncClient(
            base_url=settings.ollama_base_url.unicode_string(),
            timeout=settings.recommendation_timeout,
        ) as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
            payload: object = response.json()
    except (httpx.HTTPError, OSError, ValueError):
        return set()
    if not isinstance(payload, dict):
        return set()
    models = cast(dict[str, object], payload).get("models")
    if not isinstance(models, list):
        return set()
    return {
        name
        for item in cast(list[object], models)
        if isinstance(item, dict)
        and isinstance((name := cast(dict[str, object], item).get("name")), str)
    }


@pytest.mark.ollama
@pytest.mark.postgres
async def test_web_api_runs_and_resumes_a_real_local_ollama_workflow(
    database: Database,
    test_settings: Settings,
) -> None:
    """Exercise HTTP start, durable detail, and approval without leaking raw model output."""
    models = await installed_models(test_settings)
    required = {test_settings.embedding_model, test_settings.recommendation_model}
    if not required.issubset(models):
        pytest.skip("Embedding and chat models required for the local web API are not installed.")

    settings = test_settings.model_copy(
        update={"database_url": Secret(test_settings.test_database_url.get_secret_value())}
    )
    async with database.transaction() as session:
        project = await ProjectRepository(session).create(
            ProjectCreate(name="Web Ollama", slug=f"web-ollama-{uuid4().hex[:12]}")
        )
    thread_id = f"web-ollama-{uuid4().hex}"
    application = create_app(settings, database)

    async with open_workflow_checkpointer(
        settings,
        database_url=test_settings.test_database_url.get_secret_value(),
    ) as checkpointer:
        await setup_workflow_checkpointer(checkpointer, database)
        transport = ASGITransport(app=application, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            started = await client.post(
                "/api/v1/workflows",
                json={
                    "project_id": str(project.id),
                    "query_type": QueryType.ART.value,
                    "brief": (
                        "Create a grounded editorial art direction with deliberate negative space."
                    ),
                    "constraints": ["Keep the final recommendation concise"],
                    "provider": "ollama",
                    "thread_id": thread_id,
                },
            )
            assert started.status_code == 201
            detail = await client.get(f"/api/v1/workflows/{thread_id}")
            assert detail.status_code == 200
            payload = detail.json()
            assert payload["provider"] == "ollama"
            assert payload["model"] == settings.recommendation_model
            assert "raw_response" not in payload
            assert "embedding" not in payload

            completed = await client.post(
                f"/api/v1/workflows/{thread_id}/resume",
                json={"decision": "approve"},
            )
        assert completed.status_code == 200
        assert completed.json()["phase"] == "completed"
        await checkpointer.adelete_thread(thread_id)
