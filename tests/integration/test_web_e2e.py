"""E2E durability check for the local HTTP workflow interface."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.db.repositories import ProjectRepository
from app.db.session import Database
from app.domain.enums import QueryType
from app.domain.schemas import ProjectCreate
from app.embeddings.providers import FakeEmbeddingProvider
from app.main import create_app
from app.recommendation.factory import RecommendationProviderKind
from app.recommendation.providers import FakeRecommendationProvider
from app.recommendation.service import RecommendationService
from app.web.schemas import DependencyStatusView, ReadinessView
from app.workflow.checkpoint import open_workflow_checkpointer, setup_workflow_checkpointer
from app.workflow.persistence import WorkflowRunPersistence
from app.workflow.service import RecommendationWorkflowService
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import Secret


class ReadyForFakeWorkflows:
    """Non-network readiness used only for deterministic fake-provider E2E coverage."""

    async def get(self, _: Settings, __: Database) -> ReadinessView:
        return ReadinessView(
            ready=True,
            checked_at=datetime.now(UTC).isoformat(),
            dependencies=[
                DependencyStatusView(name=name, available=True, detail="test")
                for name in (
                    "PostgreSQL",
                    "Alembic",
                    "Workflow checkpoints",
                    "Ollama",
                    "EmbeddingGemma",
                    "Qwen",
                )
            ],
        )


def fake_workflow_factory(
    _: Settings,
    database: Database,
    checkpointer: AsyncPostgresSaver,
    *,
    provider_kind: RecommendationProviderKind,
) -> RecommendationWorkflowService:
    """Use the real durable graph with deterministic adapters for E2E isolation."""
    assert provider_kind == "fake"
    recommendation = RecommendationService(
        database,
        FakeEmbeddingProvider(),
        FakeRecommendationProvider(),
    )
    return RecommendationWorkflowService(
        checkpointer,
        recommendation,
        WorkflowRunPersistence(database, recommendation),
    )


@pytest.mark.e2e
@pytest.mark.postgres
async def test_web_workflow_survives_a_new_asgi_application_instance(
    database: Database,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revise by HTTP, recover its remaining actions in a new app, then complete."""
    settings = test_settings.model_copy(
        update={"database_url": Secret(test_settings.test_database_url.get_secret_value())}
    )
    async with database.transaction() as session:
        project = await ProjectRepository(session).create(
            ProjectCreate(name="Web E2E", slug=f"web-e2e-{uuid4().hex[:12]}")
        )
    monkeypatch.setattr("app.web.service.create_workflow_service", fake_workflow_factory)
    thread_id = f"web-e2e-{uuid4().hex}"

    async with open_workflow_checkpointer(
        settings,
        database_url=test_settings.test_database_url.get_secret_value(),
    ) as checkpointer:
        await setup_workflow_checkpointer(checkpointer, database)
        first_application = create_app(settings, database)
        first_application.state.readiness_cache = ReadyForFakeWorkflows()
        first_transport = ASGITransport(app=first_application, raise_app_exceptions=False)
        async with AsyncClient(transport=first_transport, base_url="http://test") as client:
            started = await client.post(
                "/api/v1/workflows",
                json={
                    "project_id": str(project.id),
                    "query_type": QueryType.ART.value,
                    "brief": "Persist this review across the local process restart.",
                    "provider": "fake",
                    "thread_id": thread_id,
                },
            )
            revised = await client.post(
                f"/api/v1/workflows/{thread_id}/resume",
                json={"decision": "revise", "feedback": "Keep the durable editorial framing."},
            )
        assert started.status_code == 201
        assert revised.status_code == 200
        assert revised.json()["phase"] == "waiting_for_human"
        assert revised.json()["revision_count"] == 1
        assert revised.json()["actions"] == {
            "can_approve": True,
            "can_revise": False,
            "can_reject": True,
            "can_reconcile": False,
        }
        run_id = started.json()["workflow"]["run_id"]

        second_application = create_app(settings, database)
        second_application.state.readiness_cache = ReadyForFakeWorkflows()
        second_transport = ASGITransport(app=second_application, raise_app_exceptions=False)
        async with AsyncClient(transport=second_transport, base_url="http://test") as client:
            recovered = await client.get(f"/api/v1/workflows/{thread_id}")
            assert recovered.status_code == 200
            assert recovered.json()["run_id"] == run_id
            assert recovered.json()["phase"] == "waiting_for_human"
            assert recovered.json()["actions"] == {
                "can_approve": True,
                "can_revise": False,
                "can_reject": True,
                "can_reconcile": False,
            }

            completed = await client.post(
                f"/api/v1/workflows/{thread_id}/resume",
                json={"decision": "approve"},
            )
        assert completed.status_code == 200
        assert completed.json()["phase"] == "completed"
        assert completed.json()["run_status"] == "completed"
        assert completed.json()["workflow_outcome"] == "approve"
        await checkpointer.adelete_thread(thread_id)
