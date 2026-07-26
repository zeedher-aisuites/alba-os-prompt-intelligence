"""Composition root for the durable recommendation workflow."""

from __future__ import annotations

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import Settings
from app.db.session import Database
from app.embeddings.factory import create_embedding_provider
from app.recommendation.context import RecommendationContextBuilder
from app.recommendation.factory import (
    RecommendationProviderKind,
    create_recommendation_provider,
)
from app.recommendation.service import RecommendationService
from app.workflow.persistence import WorkflowRunPersistence
from app.workflow.service import RecommendationWorkflowService


def create_workflow_service(
    settings: Settings,
    database: Database,
    checkpointer: AsyncPostgresSaver,
    *,
    provider_kind: RecommendationProviderKind,
) -> RecommendationWorkflowService:
    """Build runtime dependencies without putting them into graph state."""
    recommendation = RecommendationService(
        database,
        create_embedding_provider(settings, "ollama"),
        create_recommendation_provider(settings, provider_kind),
        context_builder=RecommendationContextBuilder(
            maximum_characters=settings.recommendation_context_max_characters,
            evidence_field_maximum=settings.recommendation_evidence_field_max_characters,
        ),
        maximum_retrieval_limit=settings.retrieval_max_limit,
    )
    persistence = WorkflowRunPersistence(database, recommendation)
    return RecommendationWorkflowService(
        checkpointer,
        recommendation,
        persistence,
        maximum_revisions=settings.workflow_max_revisions,
        diagnostics_enabled=settings.workflow_diagnostics,
    )
