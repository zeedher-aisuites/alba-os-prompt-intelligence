"""Async repository for prompt examples."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.prompt_example import PromptExample
from app.domain.enums import GenerationStatus
from app.domain.exceptions import ConstraintViolationError, EntityNotFoundError
from app.domain.schemas import PromptExampleCreate, PromptExampleUpdate


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
