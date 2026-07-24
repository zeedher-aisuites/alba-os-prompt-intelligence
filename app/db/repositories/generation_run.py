"""Async repository for recommendation generation runs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.generation_run import GenerationRun
from app.domain.enums import RunStatus
from app.domain.exceptions import (
    ConstraintViolationError,
    EntityNotFoundError,
    InvalidRunTransitionError,
)
from app.domain.schemas import GenerationRunComplete, GenerationRunCreate, GenerationRunFail


class GenerationRunRepository:
    """Generation-run persistence within caller-owned short transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: GenerationRunCreate) -> GenerationRun:
        """Create a pending or running recommendation run."""
        if data.status not in {RunStatus.PENDING, RunStatus.RUNNING}:
            raise InvalidRunTransitionError("new", "new", data.status.value)
        run = GenerationRun(**data.model_dump())
        self._session.add(run)
        await self._flush(run)
        return run

    async def get_by_id(self, run_id: UUID) -> GenerationRun | None:
        """Read one run without loading its project implicitly."""
        return await self._session.get(GenerationRun, run_id)

    async def list_by_project(
        self,
        project_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[GenerationRun]:
        """List recent runs for one project."""
        statement = (
            select(GenerationRun)
            .where(GenerationRun.project_id == project_id)
            .order_by(GenerationRun.created_at.desc(), GenerationRun.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self._session.scalars(statement)).all())

    async def mark_running(self, run_id: UUID) -> GenerationRun:
        """Move a pending run to running."""
        run = await self._require(run_id)
        self._require_status(run, {RunStatus.PENDING}, RunStatus.RUNNING)
        run.status = RunStatus.RUNNING
        await self._flush(run)
        return run

    async def mark_completed(
        self,
        run_id: UUID,
        data: GenerationRunComplete,
    ) -> GenerationRun:
        """Persist a validated recommendation and complete the run."""
        run = await self._require(run_id)
        self._require_status(run, {RunStatus.RUNNING}, RunStatus.COMPLETED)
        run.prompt_recommendation = cast(dict[str, object], data.prompt_recommendation)
        run.provider_parameters = cast(dict[str, object], data.provider_parameters)
        run.latency_ms = data.latency_ms
        run.status = RunStatus.COMPLETED
        run.error_code = None
        run.completed_at = datetime.now(UTC)
        await self._flush(run)
        return run

    async def mark_failed(
        self,
        run_id: UUID,
        data: GenerationRunFail,
    ) -> GenerationRun:
        """Record a stable failure code without stack traces or provider payloads."""
        run = await self._require(run_id)
        self._require_status(
            run,
            {RunStatus.PENDING, RunStatus.RUNNING},
            RunStatus.FAILED,
        )
        run.status = RunStatus.FAILED
        run.error_code = data.error_code
        run.latency_ms = data.latency_ms
        run.completed_at = datetime.now(UTC)
        await self._flush(run)
        return run

    async def _require(self, run_id: UUID) -> GenerationRun:
        statement = select(GenerationRun).where(GenerationRun.id == run_id).with_for_update()
        run = await self._session.scalar(statement)
        if run is None:
            raise EntityNotFoundError("GenerationRun", run_id)
        return run

    @staticmethod
    def _require_status(
        run: GenerationRun,
        allowed: set[RunStatus],
        target: RunStatus,
    ) -> None:
        if run.status not in allowed:
            raise InvalidRunTransitionError(run.id, run.status.value, target.value)

    async def _flush(self, run: GenerationRun) -> None:
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ConstraintViolationError("generation run") from exc
        await self._session.refresh(run)
