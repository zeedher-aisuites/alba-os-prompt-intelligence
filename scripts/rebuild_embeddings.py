"""Rebuild missing or stale prompt-example embeddings."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import cast

from app.core.config import get_settings
from app.db.session import Database
from app.domain.enums import GenerationStatus
from app.embeddings.factory import EmbeddingProviderKind, create_embedding_provider
from app.services.embedding_indexing import EmbeddingIndexingService


def parse_args() -> argparse.Namespace:
    """Parse explicit indexing scope and behavior."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Project slug to index")
    parser.add_argument(
        "--status",
        choices=[status.value for status in GenerationStatus],
        help="Optional prompt-example status",
    )
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--provider",
        choices=("ollama", "fake"),
        default="ollama",
        help="Ollama is the production target; fake is diagnostic only",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    """Execute one caller-owned indexing transaction."""
    settings = get_settings()
    provider_kind = cast(EmbeddingProviderKind, args.provider)
    provider = create_embedding_provider(settings, provider_kind)
    status = GenerationStatus(args.status) if args.status is not None else None
    batch_size = args.batch_size if args.batch_size is not None else settings.embedding_batch_size
    database = Database(settings)
    try:
        async with database.transaction() as session:
            report = await EmbeddingIndexingService(session, provider).rebuild(
                project_slug=args.project,
                status=status,
                batch_size=batch_size,
                force=args.force,
                dry_run=args.dry_run,
            )
        print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
    finally:
        await database.dispose()


def main() -> None:
    """Run the async indexer from a synchronous CLI."""
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
