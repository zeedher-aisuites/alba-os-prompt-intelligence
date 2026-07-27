"""Async repository for projects."""

from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.project import Project
from app.domain.exceptions import (
    ConstraintViolationError,
    DuplicateSlugError,
    EntityNotFoundError,
    ResourceInUseError,
)
from app.domain.schemas import ProjectCreate, ProjectUpdate

PROJECT_SLUG_CONSTRAINT = "uq_projects_slug"


class ProjectRepository:
    """Project persistence operations within a caller-owned transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: ProjectCreate) -> Project:
        """Insert and flush a project."""
        project = Project(**data.model_dump())
        self._session.add(project)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if PROJECT_SLUG_CONSTRAINT in str(exc):
                raise DuplicateSlugError(data.slug) from exc
            raise ConstraintViolationError("project") from exc
        await self._session.refresh(project)
        return project

    async def get_by_id(self, project_id: UUID) -> Project | None:
        """Find a project by UUID."""
        return await self._session.get(Project, project_id)

    async def get_by_slug(self, slug: str) -> Project | None:
        """Find a project by its stable slug."""
        statement = select(Project).where(Project.slug == slug)
        return await self._session.scalar(statement)

    async def list(self, *, offset: int = 0, limit: int = 100) -> list[Project]:
        """List projects newest first."""
        statement = select(Project).order_by(Project.created_at.desc()).offset(offset).limit(limit)
        return list((await self._session.scalars(statement)).all())

    async def list_by_ids(self, project_ids: Collection[UUID]) -> list[Project]:
        """Read an explicit project set for a bounded presenter mapping."""
        if not project_ids:
            return []
        statement = select(Project).where(Project.id.in_(project_ids))
        return list((await self._session.scalars(statement)).all())

    async def update(self, project_id: UUID, data: ProjectUpdate) -> Project:
        """Apply a validated partial update."""
        project = await self._require(project_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(project, field, value)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if PROJECT_SLUG_CONSTRAINT in str(exc):
                raise DuplicateSlugError(data.slug or project.slug) from exc
            raise ConstraintViolationError("project") from exc
        await self._session.refresh(project)
        return project

    async def delete(self, project_id: UUID) -> None:
        """Delete an empty project; dependent records intentionally block it."""
        project = await self._require(project_id)
        await self._session.delete(project)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ResourceInUseError("Project", project_id) from exc

    async def _require(self, project_id: UUID) -> Project:
        project = await self.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project", project_id)
        return project
