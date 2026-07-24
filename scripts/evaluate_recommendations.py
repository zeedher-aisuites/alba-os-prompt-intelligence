"""Evaluate structured recommendation objectively over fourteen fixed briefs."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import cast

from app.core.config import get_settings
from app.db.repositories import ProjectRepository
from app.db.session import Database
from app.domain.exceptions import EntityNotFoundError
from app.embeddings.factory import create_embedding_provider
from app.recommendation.context import RecommendationContextBuilder
from app.recommendation.evaluation import RecommendationEvaluationRunner
from app.recommendation.factory import (
    RecommendationProviderKind,
    create_recommendation_provider,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="retrieval-evaluation-lab")
    parser.add_argument("--provider", choices=("fake", "ollama"), default="fake")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    database = Database(settings)
    try:
        async with database.transaction() as session:
            project = await ProjectRepository(session).get_by_slug(args.project)
            if project is None:
                raise EntityNotFoundError("Project", args.project)
            project_id = project.id
        provider_kind = cast(RecommendationProviderKind, args.provider)
        report = await RecommendationEvaluationRunner(
            database,
            create_embedding_provider(settings, "ollama"),
            create_recommendation_provider(settings, provider_kind),
            context_builder=RecommendationContextBuilder(
                maximum_characters=settings.recommendation_context_max_characters,
                evidence_field_maximum=(settings.recommendation_evidence_field_max_characters),
            ),
        ).run(project_id)
        print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    finally:
        await database.dispose()


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
