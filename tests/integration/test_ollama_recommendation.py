"""Opt-in end-to-end recommendation check for a pre-installed Ollama chat model."""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from app.core.config import Settings
from app.db.repositories import GenerationRunRepository, ProjectRepository
from app.db.session import Database
from app.domain.enums import QueryType, RunStatus
from app.embeddings.providers import FakeEmbeddingProvider
from app.evaluation.demo_data import DEMO_PROJECT_SLUG
from app.recommendation.context import RecommendationContextBuilder
from app.recommendation.exceptions import RecommendationError
from app.recommendation.providers import OllamaRecommendationProvider
from app.recommendation.schemas import RecommendationRequest
from app.recommendation.service import RecommendationService
from app.services.embedding_indexing import EmbeddingIndexingService
from scripts.seed_retrieval_demo import seed_retrieval_demo


async def installed_model_names(settings: Settings) -> set[str]:
    """Read local tags without downloading or changing Ollama state."""
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
    payload = cast(dict[str, object], payload_object)
    models = payload.get("models")
    if not isinstance(models, list):
        return set()
    names: set[str] = set()
    for item_object in cast(list[object], models):
        if not isinstance(item_object, dict):
            continue
        item = cast(dict[str, object], item_object)
        name = item.get("name")
        if isinstance(name, str):
            names.add(name)
    return names


@pytest.mark.ollama
@pytest.mark.postgres
async def test_real_ollama_chat_recommendation_is_grounded_and_persisted(
    database: Database,
    test_settings: Settings,
) -> None:
    available = await installed_model_names(test_settings)
    if test_settings.recommendation_model not in available:
        pytest.skip(
            f"Ollama chat model '{test_settings.recommendation_model}' is not installed; "
            f"install it explicitly with `ollama pull {test_settings.recommendation_model}`."
        )

    await seed_retrieval_demo(database)
    embedding_provider = FakeEmbeddingProvider()
    async with database.transaction() as session:
        await EmbeddingIndexingService(session, embedding_provider).rebuild(
            project_slug=DEMO_PROJECT_SLUG
        )
        project = await ProjectRepository(session).get_by_slug(DEMO_PROJECT_SLUG)
        assert project is not None
        project_id = project.id

    provider = OllamaRecommendationProvider(
        base_url=test_settings.ollama_base_url.unicode_string(),
        model_name=test_settings.recommendation_model,
        timeout_seconds=test_settings.recommendation_timeout,
        maximum_output_tokens=test_settings.recommendation_max_output_tokens,
        maximum_repair_attempts=test_settings.recommendation_max_repair_attempts,
    )
    service = RecommendationService(
        database,
        embedding_provider,
        provider,
        context_builder=RecommendationContextBuilder(
            maximum_characters=test_settings.recommendation_context_max_characters,
            evidence_field_maximum=(test_settings.recommendation_evidence_field_max_characters),
        ),
    )
    try:
        result = await service.recommend(
            RecommendationRequest(
                project_id=project_id,
                brief="Preserve the virtual host face, cobalt outfit, and dark hairstyle.",
                query_type=QueryType.AI_INFLUENCER,
                constraints=["Do not change the established identity"],
                positive_limit=3,
                failure_limit=3,
            )
        )
    except RecommendationError as error:
        assert error.error_code in {
            "POSITIVE_EVIDENCE_CITATION_MISSING",
            "RECOMMENDATION_RESPONSE_INVALID",
            "CONSTRAINT_ACCOUNTING_INVALID",
            "FABRICATED_EVIDENCE_REFERENCE",
            "FABRICATED_CONSTRAINT_REFERENCE",
            "EVIDENCE_STATUS_MISMATCH",
        }
        async with database.transaction() as session:
            runs = await GenerationRunRepository(session).list_by_project(project_id)
        assert len(runs) == 1
        assert runs[0].status is RunStatus.FAILED
        assert runs[0].error_code == error.error_code
        assert runs[0].prompt_recommendation == {}
        assert provider.repair_attempts_used == test_settings.recommendation_max_repair_attempts
        print(f"ollama_real_recommendation_route=safe_failure_after_repair:{error.error_code}")
        return

    positive_ids = {item.example_id for item in result.positive_evidence}
    failure_ids = {item.example_id for item in result.failure_evidence}
    assert set(result.recommendation.used_positive_evidence_ids).issubset(positive_ids)
    assert result.recommendation.used_positive_evidence_ids
    assert {item.evidence_id for item in result.recommendation.failure_warnings}.issubset(
        failure_ids
    )
    assert result.recommendation.covered_constraint_ids == ["C1"]
    assert result.recommendation.unmet_constraint_ids == []
    assert result.recommendation.provider == "ollama"
    assert result.recommendation.model == test_settings.recommendation_model

    async with database.transaction() as session:
        stored = await GenerationRunRepository(session).get_by_id(result.run_id)

    assert stored is not None
    assert stored.status is RunStatus.COMPLETED
    assert stored.prompt_recommendation["recommended_prompt"]
    assert stored.prompt_recommendation["used_positive_evidence_ids"]
    assert stored.prompt_recommendation["covered_constraint_ids"] == ["C1"]
    confidence = stored.prompt_recommendation["confidence"]
    assert isinstance(confidence, int | float)
    assert confidence <= 1
    route = "success_direct" if provider.repair_attempts_used == 0 else "success_after_repair"
    print(f"ollama_real_recommendation_route={route}")
