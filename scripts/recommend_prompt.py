"""Generate and persist one retrieval-backed structured prompt recommendation."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import cast

from app.core.config import get_settings
from app.core.exceptions import AlbaError
from app.db.repositories import ProjectRepository
from app.db.session import Database
from app.domain.enums import QueryType
from app.domain.exceptions import EntityNotFoundError
from app.embeddings.factory import create_embedding_provider
from app.recommendation.context import RecommendationContextBuilder
from app.recommendation.exceptions import RecommendationError
from app.recommendation.factory import (
    RecommendationProviderKind,
    create_recommendation_provider,
)
from app.recommendation.schemas import RecommendationRequest
from app.recommendation.service import RecommendationService


def parse_args() -> argparse.Namespace:
    """Parse one explicit recommendation request."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Existing project slug")
    parser.add_argument(
        "--query-type",
        choices=[item.value for item in QueryType],
        required=True,
    )
    parser.add_argument("--brief", required=True)
    parser.add_argument("--platform")
    parser.add_argument("--method")
    parser.add_argument("--constraint", action="append", default=[])
    parser.add_argument("--positive-limit", type=int, default=5)
    parser.add_argument("--failure-limit", type=int, default=5)
    parser.add_argument("--minimum-similarity", type=float)
    parser.add_argument("--trace-id")
    parser.add_argument(
        "--provider",
        choices=("fake", "ollama"),
        default="fake",
        help="Recommendation provider; retrieval still uses configured EmbeddingGemma",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    """Resolve the project, generate outside write transactions, and print JSON."""
    settings = get_settings()
    database = Database(settings)
    try:
        async with database.transaction() as session:
            project = await ProjectRepository(session).get_by_slug(args.project)
            if project is None:
                raise EntityNotFoundError("Project", args.project)
            project_id = project.id

        request = RecommendationRequest(
            project_id=project_id,
            brief=args.brief,
            query_type=QueryType(args.query_type),
            target_platform=args.platform,
            generation_method=args.method,
            constraints=list(args.constraint),
            positive_limit=args.positive_limit,
            failure_limit=args.failure_limit,
            minimum_similarity=args.minimum_similarity,
            trace_id=args.trace_id,
        )
        provider_kind = cast(RecommendationProviderKind, args.provider)
        service = RecommendationService(
            database,
            create_embedding_provider(settings, "ollama"),
            create_recommendation_provider(settings, provider_kind),
            context_builder=RecommendationContextBuilder(
                maximum_characters=settings.recommendation_context_max_characters,
                evidence_field_maximum=(settings.recommendation_evidence_field_max_characters),
            ),
            maximum_retrieval_limit=settings.retrieval_max_limit,
        )
        result = await service.recommend(request)
        print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
        return 0
    except RecommendationError as exc:
        print(
            json.dumps(
                {"error_code": exc.error_code, "message": str(exc)},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    except AlbaError as exc:
        print(
            json.dumps(
                {
                    "error_code": exc.detail.error_code,
                    "message": exc.detail.message,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        await database.dispose()


def main() -> None:
    raise SystemExit(asyncio.run(run(parse_args())))


if __name__ == "__main__":
    main()
