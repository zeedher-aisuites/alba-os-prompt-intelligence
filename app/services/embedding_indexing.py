"""Idempotent prompt-example embedding indexing."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.constants import EMBEDDING_DIMENSIONS
from app.db.models.prompt_example import PromptExample
from app.db.repositories.prompt_example import PromptExampleRepository
from app.domain.enums import GenerationStatus
from app.domain.schemas import EmbeddingIndexingReport
from app.embeddings.builder import (
    EmbeddingDocument,
    EmbeddingTextBuilder,
    EmbeddingTextSource,
)
from app.embeddings.exceptions import EmbeddingDimensionError
from app.embeddings.protocol import EmbeddingProvider


def is_embedding_stale(
    example: PromptExample,
    document: EmbeddingDocument,
    provider: EmbeddingProvider,
    *,
    force: bool = False,
) -> bool:
    """Return whether the derived vector must be regenerated."""
    return (
        force
        or example.embedding is None
        or example.embedding_provider != provider.provider_name
        or example.embedding_model != provider.model_name
        or example.embedding_source_hash != document.source_hash
        or example.embedded_at is None
    )


def _batches[T](items: Sequence[T], batch_size: int) -> list[Sequence[T]]:
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


class EmbeddingIndexingService:
    """Coordinate canonical text, stale detection, provider calls, and persistence."""

    def __init__(
        self,
        session: AsyncSession,
        provider: EmbeddingProvider,
        *,
        builder: EmbeddingTextBuilder | None = None,
    ) -> None:
        self._session = session
        self._provider = provider
        self._builder = builder or EmbeddingTextBuilder()
        self._repository = PromptExampleRepository(session)

    async def rebuild(
        self,
        *,
        project_slug: str | None = None,
        status: GenerationStatus | None = None,
        batch_size: int = 16,
        force: bool = False,
        dry_run: bool = False,
    ) -> EmbeddingIndexingReport:
        """Index selected examples, leaving commit or rollback to the caller."""
        if batch_size < 1:
            raise ValueError("Batch size must be positive.")
        if self._provider.dimensions != EMBEDDING_DIMENSIONS:
            raise EmbeddingDimensionError(
                f"Provider dimension {self._provider.dimensions} does not match "
                f"schema dimension {EMBEDDING_DIMENSIONS}."
            )

        examples = await self._repository.list_for_embedding_index(
            project_slug=project_slug,
            status=status,
        )
        pending: list[tuple[PromptExample, EmbeddingDocument]] = []
        for example in examples:
            document = self._builder.build(self._source(example))
            if is_embedding_stale(example, document, self._provider, force=force):
                pending.append((example, document))

        if dry_run:
            return self._report(
                selected=len(examples),
                stale=len(pending),
                embedded=0,
                would_embed=len(pending),
                skipped=len(examples) - len(pending),
                batches=0,
                dry_run=True,
                force=force,
            )

        completed_batches = 0
        for batch in _batches(pending, batch_size):
            vectors = await self._provider.embed_documents([document.text for _, document in batch])
            embedded_at = datetime.now(UTC)
            for (example, document), vector in zip(batch, vectors, strict=True):
                example.embedding_text = document.text
                example.embedding = vector
                example.embedding_provider = self._provider.provider_name
                example.embedding_model = self._provider.model_name
                example.embedding_source_hash = document.source_hash
                example.embedded_at = embedded_at
            await self._session.flush()
            completed_batches += 1

        return self._report(
            selected=len(examples),
            stale=len(pending),
            embedded=len(pending),
            would_embed=0,
            skipped=len(examples) - len(pending),
            batches=completed_batches,
            dry_run=False,
            force=force,
        )

    def _source(self, example: PromptExample) -> EmbeddingTextSource:
        return EmbeddingTextSource(
            project=example.project.name,
            query_type=example.query_type,
            expected_result=example.expected_result,
            generated_image_description=example.generated_image_description,
            base_prompt=example.base_prompt,
            generation_method=example.generation_method,
            target_platform=example.target_platform,
            status=example.status,
            review_notes=example.review_notes,
            rejection_reason=example.rejection_reason,
            tags=tuple(example.tags),
        )

    def _report(
        self,
        *,
        selected: int,
        stale: int,
        embedded: int,
        would_embed: int,
        skipped: int,
        batches: int,
        dry_run: bool,
        force: bool,
    ) -> EmbeddingIndexingReport:
        return EmbeddingIndexingReport(
            provider=self._provider.provider_name,
            model=self._provider.model_name,
            dimensions=self._provider.dimensions,
            selected=selected,
            stale=stale,
            embedded=embedded,
            would_embed=would_embed,
            skipped=skipped,
            batches=batches,
            dry_run=dry_run,
            forced=force,
        )
