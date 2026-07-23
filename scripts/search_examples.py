"""Run one exact positive or failure-pattern retrieval query."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import cast
from uuid import UUID

from app.core.config import get_settings
from app.db.session import Database
from app.domain.enums import QueryType
from app.domain.schemas import RetrievalQuery
from app.embeddings.factory import EmbeddingProviderKind, create_embedding_provider
from app.retrieval.service import RetrievalService


def parse_args() -> argparse.Namespace:
    """Parse one retrieval request."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--kind", choices=("approved", "failure"), required=True)
    parser.add_argument("--project-id")
    parser.add_argument("--query-type", choices=[item.value for item in QueryType])
    parser.add_argument("--target-platform")
    parser.add_argument("--minimum-similarity", type=float)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--provider", choices=("ollama", "fake"), default="ollama")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    """Execute exact search inside a read-only unit of work."""
    settings = get_settings()
    provider = create_embedding_provider(
        settings,
        cast(EmbeddingProviderKind, args.provider),
    )
    query = RetrievalQuery(
        text=args.query,
        project_id=UUID(args.project_id) if args.project_id else None,
        query_type=QueryType(args.query_type) if args.query_type else None,
        target_platform=args.target_platform,
        minimum_similarity=args.minimum_similarity,
        limit=args.limit,
    )
    database = Database(settings)
    try:
        async with database.transaction() as session:
            service = RetrievalService(
                session,
                provider,
                maximum_limit=settings.retrieval_max_limit,
            )
            if args.kind == "approved":
                result = await service.search_approved_examples(query)
            else:
                result = await service.search_failure_patterns(query)
        print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
    finally:
        await database.dispose()


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
