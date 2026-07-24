"""Separate positive-evidence and failure-pattern retrieval operations."""

from __future__ import annotations

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.prompt_example import PromptExampleRepository
from app.domain.enums import GenerationStatus
from app.domain.schemas import (
    RetrievalQuery,
    RetrievalResultSet,
    RetrievedPromptExample,
)
from app.embeddings.protocol import EmbeddingProvider


class RetrievalService:
    """Embed a query and run exact cosine search against PostgreSQL."""

    def __init__(
        self,
        session: AsyncSession,
        provider: EmbeddingProvider,
        *,
        maximum_limit: int = 20,
    ) -> None:
        if maximum_limit < 1:
            raise ValueError("Maximum retrieval limit must be positive.")
        self._provider = provider
        self._maximum_limit = maximum_limit
        self._repository = PromptExampleRepository(session)

    async def search_approved_examples(
        self,
        query: RetrievalQuery,
    ) -> RetrievalResultSet:
        """Retrieve only approved positive evidence."""
        return await self.search_approved_examples_by_vector(
            query,
            await self._provider.embed_query(query.text),
        )

    async def search_failure_patterns(
        self,
        query: RetrievalQuery,
    ) -> RetrievalResultSet:
        """Retrieve only rejected counterexamples."""
        return await self.search_failure_patterns_by_vector(
            query,
            await self._provider.embed_query(query.text),
        )

    async def search_approved_examples_by_vector(
        self,
        query: RetrievalQuery,
        query_vector: list[float],
    ) -> RetrievalResultSet:
        """Retrieve approved evidence using a caller-supplied query vector."""
        return await self._search(
            query,
            query_vector=query_vector,
            status=GenerationStatus.APPROVED,
            retrieval_kind="approved",
        )

    async def search_failure_patterns_by_vector(
        self,
        query: RetrievalQuery,
        query_vector: list[float],
    ) -> RetrievalResultSet:
        """Retrieve rejected evidence using the same caller-supplied vector."""
        return await self._search(
            query,
            query_vector=query_vector,
            status=GenerationStatus.REJECTED,
            retrieval_kind="failure",
        )

    async def _search(
        self,
        query: RetrievalQuery,
        *,
        query_vector: list[float],
        status: GenerationStatus,
        retrieval_kind: Literal["approved", "failure"],
    ) -> RetrievalResultSet:
        applied_limit = min(query.limit, self._maximum_limit)
        rows = await self._repository.search_similar(
            query_vector,
            status=status,
            project_id=query.project_id,
            query_type=query.query_type,
            target_platform=query.target_platform,
            minimum_similarity=query.minimum_similarity,
            limit=applied_limit,
        )
        items = [
            RetrievedPromptExample(
                id=example.id,
                project_id=example.project_id,
                base_prompt=example.base_prompt,
                expected_result=example.expected_result,
                generated_image_description=example.generated_image_description,
                generation_method=example.generation_method,
                target_platform=example.target_platform,
                query_type=example.query_type,
                status=example.status,
                review_notes=example.review_notes,
                rejection_reason=example.rejection_reason,
                quality_score=example.quality_score,
                tags=list(example.tags),
                similarity=max(-1.0, min(1.0, similarity)),
            )
            for example, similarity in rows
        ]
        return RetrievalResultSet(
            retrieval_kind=retrieval_kind,
            provider=self._provider.provider_name,
            model=self._provider.model_name,
            query_text=query.text,
            requested_limit=query.limit,
            applied_limit=applied_limit,
            evidence_count=len(items),
            insufficient_evidence=not items,
            items=items,
        )
