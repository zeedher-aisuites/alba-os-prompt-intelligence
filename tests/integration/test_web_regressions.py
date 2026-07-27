"""Real PostgreSQL regressions for the Stage 5 local web delivery layer."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from app.core.config import Settings
from app.db.models.generation_run import GenerationRun
from app.db.repositories import GenerationRunRepository, ProjectRepository, PromptExampleRepository
from app.db.session import Database
from app.domain.enums import GenerationStatus, QueryType
from app.domain.schemas import (
    GenerationRunComplete,
    GenerationRunCreate,
    GenerationRunProgress,
    ProjectCreate,
    PromptExampleCreate,
)
from app.embeddings.providers import FakeEmbeddingProvider
from app.main import create_app
from app.recommendation.factory import RecommendationProviderKind
from app.recommendation.providers import FakeRecommendationProvider
from app.recommendation.service import RecommendationService
from app.web.schemas import DependencyStatusView
from app.workflow.checkpoint import open_workflow_checkpointer, setup_workflow_checkpointer
from app.workflow.persistence import WorkflowRunPersistence
from app.workflow.service import RecommendationWorkflowService
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import PostgresDsn, Secret, TypeAdapter


def fake_workflow_factory(
    _: Settings,
    database: Database,
    checkpointer: AsyncPostgresSaver,
    *,
    provider_kind: RecommendationProviderKind,
) -> RecommendationWorkflowService:
    """Exercise the durable graph with deterministic provider adapters."""
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


async def fake_ollama_statuses(_: Settings) -> list[DependencyStatusView]:
    """Avoid a network dependency while leaving database/checkpointer probes real."""
    return [
        DependencyStatusView(name=name, available=True, detail="test")
        for name in ("Ollama", "EmbeddingGemma", "Qwen")
    ]


def _client(application: object) -> AsyncClient:
    """Build an in-process client with production exception serialization enabled."""
    return AsyncClient(
        transport=ASGITransport(app=application, raise_app_exceptions=False),  # type: ignore[arg-type]
        base_url="http://test",
    )


async def _library_fixture(database: Database) -> tuple[UUID, UUID, list[UUID]]:
    """Insert data whose individual filters and intersections are unambiguous."""
    async with database.transaction() as session:
        projects = ProjectRepository(session)
        examples = PromptExampleRepository(session)
        alpha = await projects.create(
            ProjectCreate(name="Alpha Studio", slug=f"alpha-{uuid4().hex[:10]}")
        )
        beta = await projects.create(
            ProjectCreate(name="Beta Brand", slug=f"beta-{uuid4().hex[:10]}")
        )
        first = await examples.create(
            PromptExampleCreate(
                project_id=alpha.id,
                base_prompt="Cobalt editorial portrait with a preserved face.",
                expected_result="A clear cobalt editorial portrait.",
                generation_method="text_to_image",
                target_platform="OpenAI",
                query_type=QueryType.AI_INFLUENCER,
                status=GenerationStatus.APPROVED,
                tags=["Cobalt", "Editorial", "identity-preservation", "<unsafe-tag>"],
                embedding_text="Cobalt editorial portrait",
            )
        )
        second = await examples.create(
            PromptExampleCreate(
                project_id=alpha.id,
                base_prompt="Readable cobalt logo with disciplined proportions.",
                expected_result="A legible logo.",
                generation_method="text-to-image",
                target_platform="openai",
                query_type=QueryType.LOGO,
                status=GenerationStatus.REJECTED,
                rejection_reason="Typography drift",
                tags=["cobalt", "Brand", "Identity_preservation"],
                embedding_text="Cobalt logo",
            )
        )
        third = await examples.create(
            PromptExampleCreate(
                project_id=beta.id,
                base_prompt="Marketing scene with editorial framing.",
                expected_result="A polished marketing image.",
                generation_method="image_to_video",
                target_platform="PixVerse",
                query_type=QueryType.MARKETING,
                status=GenerationStatus.IN_REVIEW,
                tags=["Cobaltx", "Editorial"],
                embedding_text="Marketing editorial scene",
            )
        )
        fourth = await examples.create(
            PromptExampleCreate(
                project_id=alpha.id,
                base_prompt="Minimal image editing experiment without labels.",
                expected_result="A clean edited composition.",
                generation_method="image-editing",
                target_platform="OpenAI",
                query_type=QueryType.ART,
                status=GenerationStatus.IN_REVIEW,
                tags=[],
                embedding_text="Minimal image editing experiment",
            )
        )
    return alpha.id, beta.id, [first.id, second.id, third.id, fourth.id]


def _json_items(payload: object) -> list[dict[str, object]]:
    """Narrow arbitrary HTTP JSON to the small list payload this test consumes."""
    values = TypeAdapter(dict[str, object]).validate_python(payload)
    return TypeAdapter(list[dict[str, object]]).validate_python(values["items"])


def _item_ids(payload: object) -> set[str]:
    return {str(item["id"]) for item in _json_items(payload)}


@pytest.mark.postgres
async def test_library_filters_are_shared_case_insensitive_and_paginated(
    database: Database,
) -> None:
    """HTML and JSON accept blank optional filters and return only real intersections."""
    alpha_id, beta_id, example_ids = await _library_fixture(database)
    application = create_app(Settings(environment="test"), database)

    async with _client(application) as client:
        blank_html = await client.get(
            "/library?project_id=&query_type=&status=&platform=&method=&tag=&text="
        )
        blank_json = await client.get(
            "/api/v1/examples?project_id=&query_type=&status=&platform=&method=&tag=&text="
        )
        assert blank_html.status_code == 200
        assert blank_json.status_code == 200
        assert _item_ids(blank_json.json()) == {str(item) for item in example_ids}

        cases = {
            f"project_id={alpha_id}": {
                str(example_ids[0]),
                str(example_ids[1]),
                str(example_ids[3]),
            },
            "query_type=AI_INFLUENCER": {str(example_ids[0])},
            "status=REJECTED": {str(example_ids[1])},
            "platform=OPENAI": {str(example_ids[0]), str(example_ids[1]), str(example_ids[3])},
            "method=text_to_image": {str(example_ids[0]), str(example_ids[1])},
            "tag=EDITORIAL": {str(example_ids[0]), str(example_ids[2])},
            "tag=identity_preservation": {str(example_ids[0]), str(example_ids[1])},
            "text=COBALT": {str(example_ids[0]), str(example_ids[1])},
            (
                f"project_id={alpha_id}&query_type=ai_influencer&status=approved"
                "&platform=openai&method=text-to-image&tag=cobalt&text=portrait"
            ): {str(example_ids[0])},
        }
        for query, expected in cases.items():
            response = await client.get(f"/api/v1/examples?{query}")
            assert response.status_code == 200
            assert _item_ids(response.json()) == expected

        no_false_positive = await client.get("/api/v1/examples?tag=cobalt")
        assert _item_ids(no_false_positive.json()) == {str(example_ids[0]), str(example_ids[1])}
        invalid = await client.get("/api/v1/examples?project_id=not-a-uuid")
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "INPUT_VALIDATION_ERROR"

        first = await client.get("/library?platform=openai&limit=1")
        middle = await client.get("/library?platform=openai&limit=1&offset=1")
        last = await client.get("/library?platform=openai&limit=1&offset=2")
        assert "Results 1-1" in first.text and "Next" in first.text and "Previous" not in first.text
        assert "Results 2-2" in middle.text and "Previous" in middle.text and "Next" in middle.text
        assert "Results 3-3" in last.text and "Previous" in last.text and "Next" not in last.text
        assert "platform=openai" in middle.text

        detail_link = f"/library/{example_ids[0]}?return_to=%2Flibrary%3Fplatform%3Dinstagram"
        detail = await client.get(detail_link)
        unsafe_detail = await client.get(
            f"/library/{example_ids[0]}?return_to=https://example.invalid"
        )
        assert 'href="/library?platform=instagram"' in detail.text
        assert 'href="/library"' in unsafe_detail.text
        project_filtered = (await client.get(f"/api/v1/examples?project_id={alpha_id}")).json()
        filtered_items = _json_items(project_filtered)
        for item in filtered_items:
            project = item["project"]
            assert isinstance(project, dict)
            assert project["id"] == str(alpha_id)
        assert str(beta_id) != str(alpha_id)


@pytest.mark.postgres
async def test_library_filter_options_are_dynamic_normalized_and_safe(
    database: Database,
) -> None:
    """Facet selects and the API share bounded PostgreSQL values without vector data."""
    alpha_id, beta_id, example_ids = await _library_fixture(database)
    application = create_app(Settings(environment="test"), database)

    async with _client(application) as client:
        options = await client.get("/api/v1/examples/filter-options")
        project_options = await client.get(f"/api/v1/examples/filter-options?project_id={alpha_id}")
        beta_project_options = await client.get(
            f"/api/v1/examples/filter-options?project_id={beta_id}"
        )
        filtered_html = await client.get("/library?platform=OPENAI&method=text_to_image&tag=COBALT")
        scoped_html = await client.get(
            f"/library?project_id={beta_id}&platform=openai&method=text-to-image&tag=cobalt",
            headers={"HX-Request": "true"},
        )
        scoped_page = await client.get(f"/library?project_id={alpha_id}&platform=openai&limit=1")
        scoped_all = await client.get(f"/library?project_id={alpha_id}&platform=&method=&tag=")
        first_detail = await client.get(f"/library/{example_ids[0]}")
        untagged_detail = await client.get(f"/library/{example_ids[3]}")

    assert (
        options.status_code
        == project_options.status_code
        == beta_project_options.status_code
        == 200
    )
    payload = options.json()
    assert payload["platforms"] == [
        {"value": "openai", "label": "OpenAI"},
        {"value": "pixverse", "label": "PixVerse"},
    ]
    assert payload["generation_methods"] == [
        {"value": "image-editing", "label": "Image editing"},
        {"value": "image-to-video", "label": "Image to video"},
        {"value": "text-to-image", "label": "Text to image"},
    ]
    tag_values = [item["value"] for item in payload["tags"]]
    alphabetical_tags = [value for value in tag_values if value[0].isalpha()]
    assert alphabetical_tags == sorted(alphabetical_tags)
    assert tag_values.count("cobalt") == 1
    assert "cobaltx" in tag_values
    assert tag_values.count("identity-preservation") == 1
    assert "<unsafe-tag>" in tag_values
    assert "embedding" not in str(payload).casefold()
    assert all(not value.startswith(("[", "{", '"')) for value in tag_values)
    assert project_options.json()["platforms"] == [{"value": "openai", "label": "OpenAI"}]
    assert project_options.json()["generation_methods"] == [
        {"value": "image-editing", "label": "Image editing"},
        {"value": "text-to-image", "label": "Text to image"},
    ]
    assert [item["value"] for item in project_options.json()["tags"]] == [
        "brand",
        "cobalt",
        "editorial",
        "identity-preservation",
        "<unsafe-tag>",
    ]
    assert beta_project_options.json()["platforms"] == [{"value": "pixverse", "label": "PixVerse"}]
    assert beta_project_options.json()["generation_methods"] == [
        {"value": "image-to-video", "label": "Image to video"}
    ]
    assert [item["value"] for item in beta_project_options.json()["tags"]] == [
        "cobaltx",
        "editorial",
    ]
    assert filtered_html.status_code == 200
    assert '<option value="openai" selected>' in filtered_html.text
    assert '<option value="text-to-image" selected>' in filtered_html.text
    assert '<option value="cobalt" selected>' in filtered_html.text
    assert "All platforms" in filtered_html.text
    assert "All generation methods" in filtered_html.text
    assert "All tags" in filtered_html.text
    assert "tag-chip" in filtered_html.text
    assert "+1 more" in filtered_html.text
    assert "&lt;unsafe-tag&gt;" in filtered_html.text
    assert "<unsafe-tag>" not in filtered_html.text
    assert scoped_html.status_code == scoped_page.status_code == scoped_all.status_code == 200
    assert 'id="library-content"' in scoped_html.text
    assert 'value="openai"' not in scoped_html.text
    assert 'value="text-to-image"' not in scoped_html.text
    assert 'value="cobalt"' not in scoped_html.text
    assert 'value="pixverse"' in scoped_html.text
    assert f'value="{beta_id}" selected' in scoped_html.text
    assert "Marketing scene with editorial framing." in scoped_html.text
    assert f"project_id={alpha_id}" in scoped_page.text
    assert "platform=openai" in scoped_page.text
    assert 'value="openai"' in scoped_all.text
    assert first_detail.status_code == untagged_detail.status_code == 200
    assert "&lt;unsafe-tag&gt;" in first_detail.text
    assert "No tags" in untagged_detail.text


@pytest.mark.postgres
async def test_workflow_history_uses_explicit_items_and_preserves_pagination_filters(
    database: Database,
) -> None:
    """A paginated view model never reaches Jinja as an iterable of field tuples."""
    async with database.transaction() as session:
        projects = ProjectRepository(session)
        runs = GenerationRunRepository(session)
        alpha = await projects.create(
            ProjectCreate(name="Workflow Alpha", slug=f"wf-a-{uuid4().hex[:10]}")
        )
        beta = await projects.create(
            ProjectCreate(name="Workflow Beta", slug=f"wf-b-{uuid4().hex[:10]}")
        )
        created: list[GenerationRun] = []
        for project, label in ((alpha, "first"), (beta, "second"), (alpha, "third")):
            created.append(
                await runs.create(
                    GenerationRunCreate(
                        project_id=project.id,
                        brief_text=f"{label} durable workflow brief",
                        prompt_recommendation={},
                        provider="fake",
                        model="fake-recommendation-v1",
                        generation_method="workflow",
                        provider_parameters={"query_type": QueryType.ART.value},
                        workflow_thread_id=f"list-{label}-{uuid4().hex[:12]}",
                    )
                )
            )
        await runs.mark_running(created[0].id)
        await runs.mark_completed(
            created[0].id,
            GenerationRunComplete(
                prompt_recommendation={},
                provider_parameters={
                    "workflow_outcome": "approve",
                    "query_type": QueryType.ART.value,
                },
                latency_ms=1,
            ),
        )
        await runs.mark_running(created[1].id)
        await runs.mark_waiting_for_human(
            created[1].id,
            GenerationRunProgress(
                prompt_recommendation={},
                provider_parameters={"query_type": QueryType.LOGO.value},
                latency_ms=1,
            ),
        )

    application = create_app(Settings(environment="test"), database)
    async with _client(application) as client:
        all_workflows = await client.get("/workflows?limit=1")
        waiting = await client.get("/workflows?status=waiting_for_human&provider=fake")
        approved = await client.get("/workflows?outcome=approve")
        second_page = await client.get("/workflows?provider=fake&limit=1&offset=1")
        invalid = await client.get("/api/v1/workflows?provider=not-a-provider")

    assert all_workflows.status_code == 200
    assert "Workflow Alpha" in all_workflows.text or "Workflow Beta" in all_workflows.text
    assert "('items'" not in all_workflows.text
    assert waiting.status_code == 200 and "Workflow Beta" in waiting.text
    assert approved.status_code == 200 and "Workflow Alpha" in approved.text
    assert "Previous" in second_page.text and "provider=fake" in second_page.text
    assert invalid.status_code == 422


@pytest.mark.postgres
async def test_readiness_opens_the_same_runtime_checkpointer_before_fake_workflow_start(
    database: Database,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A settings DSN mismatch cannot make readiness green while start uses another saver."""
    unavailable_settings_url = Secret(
        PostgresDsn("postgresql+asyncpg://alba:alba_dev@127.0.0.1:1/not-the-test-database")
    )
    settings = test_settings.model_copy(update={"database_url": unavailable_settings_url})
    async with database.transaction() as session:
        project = await ProjectRepository(session).create(
            ProjectCreate(name="Readiness workflow", slug=f"ready-{uuid4().hex[:10]}")
        )
    monkeypatch.setattr("app.web.readiness._ollama_statuses", fake_ollama_statuses)
    monkeypatch.setattr("app.web.service.create_workflow_service", fake_workflow_factory)
    application = create_app(settings, database)
    thread_id = f"ready-{uuid4().hex}"

    async with open_workflow_checkpointer(
        settings,
        database_url=database.database_url,
    ) as checkpointer:
        await setup_workflow_checkpointer(checkpointer, database)
        async with _client(application) as client:
            readiness = await client.get("/api/v1/readiness")
            started = await client.post(
                "/api/v1/workflows",
                json={
                    "project_id": str(project.id),
                    "query_type": QueryType.ART.value,
                    "brief": "Use the ready checkpointer from the effective database.",
                    "provider": "fake",
                    "thread_id": thread_id,
                },
            )
            status = await client.get(f"/api/v1/workflows/{thread_id}")

        assert readiness.status_code == 200
        assert readiness.json()["ready"] is True
        assert started.status_code == 201
        assert status.json()["phase"] == "waiting_for_human"
        await checkpointer.adelete_thread(thread_id)


@pytest.mark.postgres
async def test_web_lifespan_reopens_live_savers_across_application_instances(
    database: Database,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Start, recover, and resume through two lifespans without a retained saver."""
    settings = test_settings.model_copy(
        update={"database_url": Secret(test_settings.test_database_url.get_secret_value())}
    )
    monkeypatch.setattr("app.web.readiness._ollama_statuses", fake_ollama_statuses)
    monkeypatch.setattr("app.web.service.create_workflow_service", fake_workflow_factory)
    first_database = Database(
        settings,
        database_url=test_settings.test_database_url.get_secret_value(),
    )
    second_database: Database | None = None
    thread_id = f"lifespan-{uuid4().hex}"
    try:
        await database.check_connection()
        async with first_database.transaction() as session:
            project = await ProjectRepository(session).create(
                ProjectCreate(name="Lifespan workflow", slug=f"lifespan-{uuid4().hex[:10]}")
            )
        async with open_workflow_checkpointer(
            settings,
            database_url=first_database.database_url,
        ) as checkpointer:
            await setup_workflow_checkpointer(checkpointer, first_database)

        first_application = create_app(settings, first_database)
        async with (
            first_application.router.lifespan_context(first_application),
            _client(first_application) as client,
        ):
            readiness = await client.get("/api/v1/readiness")
            started = await client.post(
                "/api/v1/workflows",
                json={
                    "project_id": str(project.id),
                    "query_type": QueryType.ART.value,
                    "brief": "Persist through a complete application lifespan.",
                    "provider": "fake",
                    "thread_id": thread_id,
                },
            )
            waiting = await client.get(f"/api/v1/workflows/{thread_id}")
        assert readiness.json()["ready"] is True
        assert started.status_code == 201
        assert waiting.json()["phase"] == "waiting_for_human"

        second_database = Database(
            settings,
            database_url=test_settings.test_database_url.get_secret_value(),
        )
        second_application = create_app(settings, second_database)
        async with (
            second_application.router.lifespan_context(second_application),
            _client(second_application) as client,
        ):
            recovered = await client.get(f"/api/v1/workflows/{thread_id}")
            completed = await client.post(
                f"/api/v1/workflows/{thread_id}/resume",
                json={"decision": "approve"},
            )
        assert recovered.json()["phase"] == "waiting_for_human"
        assert completed.status_code == 200
        assert completed.json()["phase"] == "completed"
        assert completed.json()["run_status"] == "completed"
    finally:
        await first_database.dispose()
        if second_database is not None:
            await second_database.dispose()


@pytest.mark.postgres
async def test_web_blocks_start_when_the_shared_checkpoint_schema_is_missing(
    database: Database,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing shared schema makes readiness false and keeps the public 503 safe."""
    missing_schema = f"missing_checkpoint_{uuid4().hex[:12]}"
    settings = test_settings.model_copy(
        update={"database_url": Secret(test_settings.test_database_url.get_secret_value())}
    )
    async with database.transaction() as session:
        project = await ProjectRepository(session).create(
            ProjectCreate(name="Missing schema", slug=f"missing-schema-{uuid4().hex[:10]}")
        )
    monkeypatch.setattr("app.web.readiness.CHECKPOINT_SCHEMA", missing_schema)
    monkeypatch.setattr("app.workflow.checkpoint.CHECKPOINT_SCHEMA", missing_schema)
    monkeypatch.setattr("app.web.readiness._ollama_statuses", fake_ollama_statuses)
    monkeypatch.setattr("app.web.service.create_workflow_service", fake_workflow_factory)
    application = create_app(settings, database)

    async with (
        application.router.lifespan_context(application),
        _client(application) as client,
    ):
        readiness = await client.get("/api/v1/readiness")
        started = await client.post(
            "/api/v1/workflows",
            json={
                "project_id": str(project.id),
                "query_type": QueryType.ART.value,
                "brief": "Do not start without the configured checkpoint schema.",
                "provider": "fake",
                "thread_id": f"missing-schema-{uuid4().hex}",
            },
        )

    checkpoint = next(
        item for item in readiness.json()["dependencies"] if item["name"] == "Workflow checkpoints"
    )
    assert readiness.json()["ready"] is False
    assert checkpoint == {
        "name": "Workflow checkpoints",
        "available": False,
        "detail": "setup required",
    }
    assert started.status_code == 503
    assert started.json()["error"]["code"] == "WEB_DEPENDENCY_UNAVAILABLE"
    assert "missing_checkpoint" not in started.text


@pytest.mark.postgres
async def test_docs_and_unexpected_errors_remain_local_and_safe(database: Database) -> None:
    """Docs use checked-in assets and unknown failures do not disclose internals."""
    application = create_app(Settings(environment="test"), database)

    async def explode() -> None:
        raise RuntimeError("internal diagnostic that must not reach the browser")

    application.add_api_route("/test-unexpected-error", explode)
    application.add_api_route("/api/v1/test-unexpected-error", explode)
    async with _client(application) as client:
        docs = await client.get("/docs")
        css = await client.get("/static/swagger-ui/5.17.14/swagger-ui.css")
        javascript = await client.get("/static/swagger-ui/5.17.14/swagger-ui-bundle.js")
        openapi = await client.get("/openapi.json")
        html_error = await client.get("/test-unexpected-error", headers={"accept": "text/html"})
        api_error = await client.get("/api/v1/test-unexpected-error")

    assert docs.status_code == css.status_code == javascript.status_code == openapi.status_code
    assert docs.status_code == 200
    assert "swagger-ui-bundle.js" in docs.text
    assert "cdn" not in docs.text.casefold()
    assert "unsafe-inline" not in docs.headers["content-security-policy"]
    assert "script-src 'self'" in docs.headers["content-security-policy"]
    assert html_error.status_code == api_error.status_code == 500
    assert "internal diagnostic" not in html_error.text
    assert "traceback" not in html_error.text.casefold()
    assert "INTERNAL_SERVER_ERROR" in html_error.text
    assert api_error.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
