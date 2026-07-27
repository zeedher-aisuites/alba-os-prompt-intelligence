"""HTTP integration tests for the shared local web workflow facade."""

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
    """Test-only readiness result that avoids network calls to local Ollama."""

    async def get(self, _: Settings, __: Database) -> ReadinessView:
        return ReadinessView(
            ready=True,
            checked_at=datetime.now(UTC).isoformat(),
            dependencies=[
                DependencyStatusView(name="PostgreSQL", available=True, detail="test"),
                DependencyStatusView(name="Alembic", available=True, detail="test"),
                DependencyStatusView(name="Workflow checkpoints", available=True, detail="test"),
                DependencyStatusView(name="Ollama", available=True, detail="test"),
                DependencyStatusView(name="EmbeddingGemma", available=True, detail="test"),
                DependencyStatusView(name="Qwen", available=True, detail="test"),
            ],
        )


def fake_workflow_factory(
    _: Settings,
    database: Database,
    checkpointer: AsyncPostgresSaver,
    *,
    provider_kind: RecommendationProviderKind,
) -> RecommendationWorkflowService:
    """Build the real graph with deterministic in-process provider adapters."""
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


@pytest.mark.postgres
async def test_html_and_json_share_fake_workflow_facade(
    database: Database,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One HTTP thread reaches interrupt, escapes content, then completes safely."""
    settings = test_settings.model_copy(
        update={"database_url": Secret(test_settings.test_database_url.get_secret_value())}
    )
    async with database.transaction() as session:
        project = await ProjectRepository(session).create(
            ProjectCreate(name="Web HTTP", slug=f"web-http-{uuid4().hex[:12]}")
        )
    monkeypatch.setattr("app.web.service.create_workflow_service", fake_workflow_factory)
    application = create_app(settings, database)
    application.state.readiness_cache = ReadyForFakeWorkflows()
    thread_id = f"web-http-{uuid4().hex}"

    async with open_workflow_checkpointer(
        settings,
        database_url=test_settings.test_database_url.get_secret_value(),
    ) as checkpointer:
        await setup_workflow_checkpointer(checkpointer, database)
        transport = ASGITransport(app=application, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/workflows",
                data={
                    "project_id": str(project.id),
                    "query_type": QueryType.ART.value,
                    "brief": "<script>untrusted brief</script>",
                    "constraints": "Keep the editorial crop",
                    "provider": "fake",
                    "thread_id": thread_id,
                },
                follow_redirects=False,
            )
            assert created.status_code == 303
            assert created.headers["location"] == f"/workflows/{thread_id}"

            detail = await client.get(created.headers["location"])
            assert detail.status_code == 200
            assert "&lt;script&gt;untrusted brief&lt;/script&gt;" in detail.text
            assert "vector" not in detail.text.casefold()

            invalid_review = await client.post(
                f"/workflows/{thread_id}/resume",
                data={"decision": "revise"},
                headers={"HX-Request": "true"},
            )
            assert invalid_review.status_code == 422
            assert "Human feedback is required" in invalid_review.text
            assert "workflow-card" in invalid_review.text

            initial = await client.get(f"/api/v1/workflows/{thread_id}")
            assert initial.status_code == 200
            assert initial.json()["actions"] == {
                "can_approve": True,
                "can_revise": True,
                "can_reject": True,
                "can_reconcile": False,
            }

            duplicate = await client.post(
                "/api/v1/workflows",
                json={
                    "project_id": str(project.id),
                    "query_type": QueryType.ART.value,
                    "brief": "<script>untrusted brief</script>",
                    "constraints": ["Keep the editorial crop"],
                    "provider": "fake",
                    "thread_id": thread_id,
                },
            )
            assert duplicate.status_code == 200
            assert duplicate.json()["created"] is False

            revised_partial = await client.post(
                f"/workflows/{thread_id}/resume",
                data={"decision": "revise", "feedback": "Retain the editorial crop."},
                headers={"HX-Request": "true"},
            )
            assert revised_partial.status_code == 200
            assert "Approve" in revised_partial.text
            assert "Reject" in revised_partial.text
            assert "The single revision has already been used." in revised_partial.text
            assert 'value="revise"' not in revised_partial.text

            revised = await client.get(f"/api/v1/workflows/{thread_id}")
            assert revised.status_code == 200
            revised_payload = revised.json()
            assert revised_payload["phase"] == "waiting_for_human"
            assert revised_payload["run_status"] == "waiting_for_human"
            assert revised_payload["revision_count"] == 1
            assert revised_payload["human_decision"] == "revise"
            assert revised_payload["actions"] == {
                "can_approve": True,
                "can_revise": False,
                "can_reject": True,
                "can_reconcile": False,
            }

            refreshed = await client.get(f"/workflows/{thread_id}")
            assert refreshed.status_code == 200
            assert "Approve" in refreshed.text and "Reject" in refreshed.text
            assert "The single revision has already been used." in refreshed.text
            assert 'value="revise"' not in refreshed.text

            revision_limited = await client.post(
                f"/api/v1/workflows/{thread_id}/resume",
                json={"decision": "revise", "feedback": "A second revision must not run."},
            )
            assert revision_limited.status_code == 409
            assert revision_limited.json()["error"]["code"] == "WORKFLOW_REVISION_LIMIT"
            after_limited_revision = await client.get(f"/api/v1/workflows/{thread_id}")
            assert after_limited_revision.json()["phase"] == "waiting_for_human"
            assert after_limited_revision.json()["run_status"] == "waiting_for_human"
            assert after_limited_revision.json()["revision_count"] == 1
            assert after_limited_revision.json()["actions"] == revised_payload["actions"]

            resumed = await client.post(
                f"/api/v1/workflows/  {thread_id}  /resume",
                json={"decision": "approve"},
            )
            assert resumed.status_code == 200
            payload = resumed.json()
            assert payload["phase"] == "completed"
            assert payload["run_status"] == "completed"
            assert payload["workflow_outcome"] == "approve"
            assert payload["actions"] == {
                "can_approve": False,
                "can_revise": False,
                "can_reject": False,
                "can_reconcile": False,
            }
            assert "embedding" not in payload

            reject_thread_id = f"{thread_id}-reject"
            reject_started = await client.post(
                "/api/v1/workflows",
                json={
                    "project_id": str(project.id),
                    "query_type": QueryType.ART.value,
                    "brief": "Use the same revision rule before a safe rejection.",
                    "provider": "fake",
                    "thread_id": reject_thread_id,
                },
            )
            assert reject_started.status_code == 201
            revised_without_htmx = await client.post(
                f"/workflows/{reject_thread_id}/resume",
                data={"decision": "revise", "feedback": "Keep the original framing."},
                follow_redirects=False,
            )
            assert revised_without_htmx.status_code == 303
            reject_waiting = await client.get(revised_without_htmx.headers["location"])
            assert "Approve" in reject_waiting.text and "Reject" in reject_waiting.text
            assert "The single revision has already been used." in reject_waiting.text
            rejected = await client.post(
                f"/api/v1/workflows/{reject_thread_id}/resume",
                json={"decision": "reject", "feedback": "Reject after the one revision."},
            )
            assert rejected.status_code == 200
            assert rejected.json()["phase"] == "completed"
            assert rejected.json()["workflow_outcome"] == "reject"
            assert rejected.json()["actions"] == {
                "can_approve": False,
                "can_revise": False,
                "can_reject": False,
                "can_reconcile": False,
            }

            invalid = await client.post("/api/v1/workflows", json={"provider": "invalid"})
            assert invalid.status_code == 422
            assert invalid.json()["error"]["code"] == "INPUT_VALIDATION_ERROR"

        await checkpointer.adelete_thread(thread_id)
        await checkpointer.adelete_thread(reject_thread_id)
