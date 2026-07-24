"""Verify a LangGraph checkpoint survives a real PostgreSQL restart."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.db.repositories import ProjectRepository
from app.db.session import Database
from app.domain.enums import QueryType
from app.domain.schemas import ProjectCreate
from app.embeddings.providers import FakeEmbeddingProvider
from app.recommendation.providers import FakeRecommendationProvider
from app.recommendation.schemas import RecommendationRequest
from app.recommendation.service import RecommendationService
from app.workflow.checkpoint import (
    open_workflow_checkpointer,
    setup_workflow_checkpointer,
)
from app.workflow.persistence import WorkflowRunPersistence
from app.workflow.schemas import HumanDecision, WorkflowPhase, WorkflowResumeCommand
from app.workflow.service import RecommendationWorkflowService
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from tests.integration.test_docker_persistence import (
    run_docker,
    wait_for_postgres_health,
)


def service_for(
    database: Database,
    checkpointer: AsyncPostgresSaver,
) -> RecommendationWorkflowService:
    """Build a fake-provider runtime while retaining real PostgreSQL checkpoints."""
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
@pytest.mark.docker
@pytest.mark.postgres
async def test_workflow_checkpoint_persists_after_postgres_restart(
    database: Database,
    test_settings: Settings,
) -> None:
    async with database.transaction() as session:
        project = await ProjectRepository(session).create(
            ProjectCreate(
                name="Workflow Docker Persistence",
                slug=f"workflow-docker-{uuid4().hex[:12]}",
            )
        )
    thread_id = f"docker-workflow-{uuid4().hex}"
    checkpoint_url = test_settings.test_database_url.get_secret_value()

    async with open_workflow_checkpointer(
        test_settings,
        database_url=checkpoint_url,
    ) as checkpointer:
        await setup_workflow_checkpointer(checkpointer, database)
        started = await service_for(database, checkpointer).start(
            RecommendationRequest(
                project_id=project.id,
                brief="Create a durable workflow test portrait.",
                query_type=QueryType.OTHER,
            ),
            thread_id=thread_id,
        )

    assert started.phase is WorkflowPhase.WAITING_FOR_HUMAN
    await asyncio.to_thread(run_docker, "compose", "restart", "postgres")
    await asyncio.to_thread(wait_for_postgres_health)

    async with open_workflow_checkpointer(
        test_settings,
        database_url=checkpoint_url,
    ) as restarted_checkpointer:
        restarted_service = service_for(database, restarted_checkpointer)
        recovered = await restarted_service.status(thread_id)
        completed = await restarted_service.resume(
            thread_id,
            WorkflowResumeCommand(decision=HumanDecision.APPROVE),
        )
        await restarted_checkpointer.adelete_thread(thread_id)

    assert recovered.checkpoint_id == started.checkpoint_id
    assert recovered.phase is WorkflowPhase.WAITING_FOR_HUMAN
    assert completed.phase is WorkflowPhase.COMPLETED
