"""Opt-in real Ollama workflow through interrupt, revision, and approval."""

from __future__ import annotations

from typing import cast
from uuid import uuid4

import httpx
import pytest
from app.core.config import Settings
from app.db.repositories import GenerationRunRepository, ProjectRepository
from app.db.session import Database
from app.domain.enums import QueryType, RunStatus
from app.domain.schemas import ProjectCreate
from app.embeddings.providers import FakeEmbeddingProvider
from app.recommendation.context import RecommendationContextBuilder
from app.recommendation.providers import OllamaRecommendationProvider
from app.recommendation.schemas import RecommendationRequest
from app.recommendation.service import RecommendationService
from app.workflow.checkpoint import (
    open_workflow_checkpointer,
    setup_workflow_checkpointer,
)
from app.workflow.persistence import WorkflowRunPersistence
from app.workflow.schemas import HumanDecision, WorkflowPhase, WorkflowResumeCommand
from app.workflow.service import RecommendationWorkflowService


async def installed_models(settings: Settings) -> set[str]:
    """Read local models without pulling or mutating Ollama."""
    try:
        async with httpx.AsyncClient(
            base_url=settings.ollama_base_url.unicode_string(),
            timeout=settings.recommendation_timeout,
        ) as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
            payload_object: object = response.json()
    except (httpx.HTTPError, OSError, ValueError):
        return set()
    if not isinstance(payload_object, dict):
        return set()
    models = cast(dict[str, object], payload_object).get("models")
    if not isinstance(models, list):
        return set()
    names: set[str] = set()
    for item in cast(list[object], models):
        if isinstance(item, dict):
            name = cast(dict[str, object], item).get("name")
            if isinstance(name, str):
                names.add(name)
    return names


@pytest.mark.ollama
@pytest.mark.postgres
async def test_real_ollama_workflow_revises_and_persists(
    database: Database,
    test_settings: Settings,
) -> None:
    if test_settings.recommendation_model not in await installed_models(test_settings):
        pytest.skip(f"Ollama chat model '{test_settings.recommendation_model}' is not installed.")

    embedding = FakeEmbeddingProvider()
    async with database.transaction() as session:
        project = await ProjectRepository(session).create(
            ProjectCreate(
                name="Ollama Workflow Empty Evidence",
                slug=f"ollama-workflow-{uuid4().hex[:12]}",
            )
        )

    recommendation = RecommendationService(
        database,
        embedding,
        OllamaRecommendationProvider(
            base_url=test_settings.ollama_base_url.unicode_string(),
            model_name=test_settings.recommendation_model,
            timeout_seconds=test_settings.recommendation_timeout,
            maximum_output_tokens=test_settings.recommendation_max_output_tokens,
            maximum_repair_attempts=test_settings.recommendation_max_repair_attempts,
        ),
        context_builder=RecommendationContextBuilder(
            maximum_characters=test_settings.recommendation_context_max_characters,
            evidence_field_maximum=test_settings.recommendation_evidence_field_max_characters,
        ),
    )
    thread_id = f"ollama-workflow-{uuid4().hex}"
    async with open_workflow_checkpointer(
        test_settings,
        database_url=test_settings.test_database_url.get_secret_value(),
    ) as checkpointer:
        await setup_workflow_checkpointer(checkpointer, database)
        service = RecommendationWorkflowService(
            checkpointer,
            recommendation,
            WorkflowRunPersistence(database, recommendation),
        )
        started = await service.start(
            RecommendationRequest(
                project_id=project.id,
                brief="Preserve the virtual host face and cobalt outfit.",
                query_type=QueryType.AI_INFLUENCER,
                constraints=["Keep the established identity"],
                positive_limit=3,
                failure_limit=3,
            ),
            thread_id=thread_id,
        )
        revised = await service.resume(
            thread_id,
            WorkflowResumeCommand(
                decision=HumanDecision.REVISE,
                feedback="Make the editorial composition more explicit.",
            ),
        )
        completed = await service.resume(
            thread_id,
            WorkflowResumeCommand(decision=HumanDecision.APPROVE),
        )
        await checkpointer.adelete_thread(thread_id)

    assert started.phase is WorkflowPhase.WAITING_FOR_HUMAN
    assert revised.phase is WorkflowPhase.WAITING_FOR_HUMAN
    assert revised.revision_count == 1
    assert revised.recommendation is not None
    assert revised.recommendation.provider == "ollama"
    assert revised.recommendation.model == test_settings.recommendation_model
    assert revised.recommendation.used_positive_evidence_ids == []
    assert revised.recommendation.failure_warnings == []
    assert revised.recommendation.needs_human_review is True
    assert completed.phase is WorkflowPhase.COMPLETED
    assert completed.run_status is RunStatus.COMPLETED
    assert completed.run_id is not None

    async with database.transaction() as session:
        run = await GenerationRunRepository(session).get_by_id(completed.run_id)
    assert run is not None
    assert run.provider_parameters["workflow_outcome"] == "approve"
    assert run.provider_parameters["revision_count"] == 1
