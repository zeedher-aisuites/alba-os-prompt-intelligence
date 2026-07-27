"""Async repository for prompt examples."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from sqlalchemy import exists, func, or_, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.project import Project
from app.db.models.prompt_example import PromptExample
from app.domain.enums import GenerationStatus, QueryType
from app.domain.exceptions import ConstraintViolationError, EntityNotFoundError
from app.domain.schemas import PromptExampleCreate, PromptExampleUpdate

MAX_LIBRARY_FACET_VALUES = 200


@dataclass(frozen=True)
class LibraryFacetValues:
    """Canonical strings returned by bounded PostgreSQL facet queries."""

    platforms: list[str]
    generation_methods: list[str]
    tags: list[str]


class PromptExampleRepository:
    """Prompt-example persistence operations within one transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: PromptExampleCreate) -> PromptExample:
        """Insert an example without generating an embedding."""
        example = PromptExample(**data.model_dump(), embedding=None)
        self._session.add(example)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ConstraintViolationError("prompt example") from exc
        await self._session.refresh(example)
        return example

    async def get_by_id(self, example_id: UUID) -> PromptExample | None:
        """Find an example by UUID."""
        return await self._session.get(PromptExample, example_id)

    async def list_by_project(
        self,
        project_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[PromptExample]:
        """List examples for one project newest first."""
        statement = (
            select(PromptExample)
            .where(PromptExample.project_id == project_id)
            .order_by(PromptExample.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self._session.scalars(statement)).all())

    async def list_by_status(
        self,
        status: GenerationStatus,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[PromptExample]:
        """List examples by promotion status."""
        statement = (
            select(PromptExample)
            .where(PromptExample.status == status)
            .order_by(PromptExample.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self._session.scalars(statement)).all())

    async def list_for_library(
        self,
        *,
        project_id: UUID | None = None,
        query_type: QueryType | None = None,
        status: GenerationStatus | None = None,
        target_platform: str | None = None,
        generation_method: str | None = None,
        tag: str | None = None,
        text_query: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[PromptExample]:
        """Read prompt examples for the local library without vector retrieval."""
        statement = select(PromptExample)
        if project_id is not None:
            statement = statement.where(PromptExample.project_id == project_id)
        if query_type is not None:
            statement = statement.where(PromptExample.query_type == query_type)
        if status is not None:
            statement = statement.where(PromptExample.status == status)
        if target_platform is not None:
            statement = statement.where(
                _normalized_platform(PromptExample.target_platform) == target_platform
            )
        if generation_method is not None:
            statement = statement.where(
                _normalized_generation_method(PromptExample.generation_method) == generation_method
            )
        if tag is not None:
            tag_values = (
                func.jsonb_array_elements_text(PromptExample.tags)
                .table_valued("value")
                .alias("tag_values")
            )
            statement = statement.where(
                exists(
                    select(1)
                    .select_from(tag_values)
                    .where(_normalized_tag(tag_values.c.value) == tag)
                )
            )
        if text_query is not None:
            pattern = f"%{text_query}%"
            statement = statement.where(
                or_(
                    PromptExample.base_prompt.ilike(pattern),
                    PromptExample.expected_result.ilike(pattern),
                )
            )
        statement = (
            statement.order_by(PromptExample.created_at.desc(), PromptExample.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self._session.scalars(statement)).all())

    async def list_library_facet_values(
        self,
        *,
        project_id: UUID | None = None,
    ) -> LibraryFacetValues:
        """Read bounded distinct filter values from PostgreSQL without loading ORM rows."""
        platform_value = _normalized_platform(PromptExample.target_platform).label("value")
        platform_statement = select(platform_value).where(platform_value != "")
        method_value = _normalized_generation_method(PromptExample.generation_method).label("value")
        method_statement = select(method_value).where(method_value != "")
        if project_id is not None:
            platform_statement = platform_statement.where(PromptExample.project_id == project_id)
            method_statement = method_statement.where(PromptExample.project_id == project_id)

        tag_values = (
            func.jsonb_array_elements_text(PromptExample.tags)
            .table_valued("value")
            .alias("tag_values")
        )
        tag_value = _normalized_tag(tag_values.c.value).label("value")
        tag_statement = (
            select(tag_value)
            .select_from(PromptExample)
            .join(tag_values, true())
            .where(tag_value != "")
        )
        if project_id is not None:
            tag_statement = tag_statement.where(PromptExample.project_id == project_id)

        platforms = list(
            (
                await self._session.scalars(
                    platform_statement.distinct()
                    .order_by(platform_value)
                    .limit(MAX_LIBRARY_FACET_VALUES)
                )
            ).all()
        )
        generation_methods = list(
            (
                await self._session.scalars(
                    method_statement.distinct()
                    .order_by(method_value)
                    .limit(MAX_LIBRARY_FACET_VALUES)
                )
            ).all()
        )
        tags = list(
            (
                await self._session.scalars(
                    tag_statement.distinct().order_by(tag_value).limit(MAX_LIBRARY_FACET_VALUES)
                )
            ).all()
        )
        return LibraryFacetValues(
            platforms=[str(value) for value in platforms],
            generation_methods=[str(value) for value in generation_methods],
            tags=[str(value) for value in tags],
        )

    async def list_for_embedding_index(
        self,
        *,
        project_slug: str | None = None,
        status: GenerationStatus | None = None,
    ) -> list[PromptExample]:
        """Load embedding candidates and their projects without implicit I/O."""
        statement = (
            select(PromptExample)
            .join(Project)
            .options(selectinload(PromptExample.project))
            .order_by(PromptExample.id)
        )
        if project_slug is not None:
            statement = statement.where(Project.slug == project_slug)
        if status is not None:
            statement = statement.where(PromptExample.status == status)
        return list((await self._session.scalars(statement)).all())

    async def search_similar(
        self,
        query_embedding: Sequence[float],
        *,
        status: GenerationStatus,
        project_id: UUID | None = None,
        query_type: QueryType | None = None,
        target_platform: str | None = None,
        minimum_similarity: float | None = None,
        limit: int,
    ) -> list[tuple[PromptExample, float]]:
        """Run exact cosine search over one promotion status."""
        distance = PromptExample.embedding.cosine_distance(list(query_embedding))
        similarity = (1.0 - distance).label("similarity")
        statement = (
            select(PromptExample, similarity)
            .where(
                PromptExample.embedding.is_not(None),
                PromptExample.status == status,
            )
            .order_by(distance.asc(), PromptExample.id.asc())
            .limit(limit)
        )
        if project_id is not None:
            statement = statement.where(PromptExample.project_id == project_id)
        if query_type is not None:
            statement = statement.where(PromptExample.query_type == query_type)
        if target_platform is not None:
            statement = statement.where(PromptExample.target_platform == target_platform)
        if minimum_similarity is not None:
            statement = statement.where(similarity >= minimum_similarity)

        rows = (await self._session.execute(statement)).all()
        return [(row[0], float(row[1])) for row in rows]

    async def update(
        self,
        example_id: UUID,
        data: PromptExampleUpdate,
    ) -> PromptExample:
        """Apply a validated partial update without touching the vector."""
        example = await self._require(example_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(example, field, value)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ConstraintViolationError("prompt example") from exc
        await self._session.refresh(example)
        return example

    async def delete(self, example_id: UUID) -> None:
        """Delete an example; PostgreSQL cascades its dependent reviews."""
        example = await self._require(example_id)
        await self._session.delete(example)
        await self._session.flush()

    async def _require(self, example_id: UUID) -> PromptExample:
        example = await self.get_by_id(example_id)
        if example is None:
            raise EntityNotFoundError("PromptExample", example_id)
        return example


def _normalized_platform(
    value: ColumnElement[Any] | InstrumentedAttribute[str],
) -> ColumnElement[str]:
    """SQL expression matching the shared platform normalizer."""
    return cast(
        ColumnElement[str],
        func.lower(func.regexp_replace(func.btrim(value), r"\s+", " ", "g")),
    )


def _normalized_generation_method(
    value: ColumnElement[Any] | InstrumentedAttribute[str],
) -> ColumnElement[str]:
    """SQL expression matching the shared generation-method normalizer."""
    return cast(
        ColumnElement[str],
        func.lower(func.regexp_replace(func.btrim(value), r"[\s_-]+", "-", "g")),
    )


def _normalized_tag(value: ColumnElement[Any]) -> ColumnElement[str]:
    """SQL expression matching exact, case-insensitive tag filtering."""
    return cast(
        ColumnElement[str],
        func.lower(func.regexp_replace(func.btrim(value), r"[\s_-]+", "-", "g")),
    )
