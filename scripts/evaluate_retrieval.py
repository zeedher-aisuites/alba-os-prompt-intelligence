"""Measure retrieval quality and latency over twenty deterministic cases."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import cast

from app.core.config import get_settings
from app.db.session import Database
from app.embeddings.factory import EmbeddingProviderKind, create_embedding_provider
from app.evaluation.runner import RetrievalEvaluationRunner


def parse_args() -> argparse.Namespace:
    """Select the real provider or an explicitly diagnostic fake."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("ollama", "fake"), default="ollama")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    provider = create_embedding_provider(
        settings,
        cast(EmbeddingProviderKind, args.provider),
    )
    database = Database(settings)
    try:
        async with database.transaction() as session:
            report = await RetrievalEvaluationRunner(
                session,
                provider,
                maximum_limit=settings.retrieval_max_limit,
            ).run()
        print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    finally:
        await database.dispose()


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
