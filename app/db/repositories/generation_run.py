"""Async repository for recommendation generation runs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.generation_run import GenerationRun
from app.domain.enums import RunStatus
from app.domain.exceptions import (
    ConstraintViolationError,
    EntityNotFoundError,
    InvalidRunTransitionError,
)
from app.domain.schemas import (
    GenerationRunComplete,
    GenerationRunCreate,
    GenerationRunFail,
    GenerationRunProgress,
)


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

    async def get_by_workflow_thread_id(self, thread_id: str) -> GenerationRun | None:
        """Read the business run mapped to one durable LangGraph thread."""
        statement = select(GenerationRun).where(GenerationRun.workflow_thread_id == thread_id)
        return await self._session.scalar(statement)

    async def acquire_workflow_thread_lock(self, thread_id: str) -> None:
        """Serialize competing starts for one thread for this short transaction."""
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:thread_id, 0))"),
            {"thread_id": thread_id},
        )

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

    async def claim_human_resume(self, run_id: UUID) -> GenerationRun:
        """Atomically claim a paused run before resuming its checkpoint."""
        run = await self._require(run_id)
        self._require_status(
            run,
            {RunStatus.WAITING_FOR_HUMAN},
            RunStatus.RUNNING,
        )
        run.status = RunStatus.RUNNING
        await self._flush(run)
        return run

    async def reconcile_unaccepted_human_resume(
        self,
        run_id: UUID,
        *,
        thread_id: str,
        checkpoint_id: str,
    ) -> GenerationRun:
        """Restore only a verified unaccepted resume claim to its paused state."""
        run = await self._require(run_id)
        parameters = dict(run.provider_parameters)
        if (
            run.status is not RunStatus.RUNNING
            or run.workflow_thread_id != thread_id
            or run.completed_at is not None
            or run.error_code is not None
            or parameters.get("workflow_outcome") is not None
            or parameters.get("human_decision") is not None
        ):
            raise InvalidRunTransitionError(
                run.id,
                run.status.value,
                RunStatus.WAITING_FOR_HUMAN.value,
            )

        history_value = parameters.get("resume_reconciliations", [])
        if not isinstance(history_value, list):
            raise ConstraintViolationError("workflow resume reconciliation")
        history = cast(list[object], history_value)
        history.append(
            {
                "code": "WORKFLOW_RESUME_NOT_ACCEPTED",
                "checkpoint_id": checkpoint_id,
                "reconciled_at": datetime.now(UTC).isoformat(),
            }
        )
        parameters["resume_reconciliations"] = history[-10:]
        parameters["workflow_phase"] = RunStatus.WAITING_FOR_HUMAN.value
        parameters["human_decision"] = None
        run.provider_parameters = parameters
        run.status = RunStatus.WAITING_FOR_HUMAN
        await self._flush(run)
        return run

    async def mark_waiting_for_human(
        self,
        run_id: UUID,
        data: GenerationRunProgress,
    ) -> GenerationRun:
        """Persist safe review data and release the run for an indefinite pause."""
        run = await self._require(run_id)
        if run.status is RunStatus.WAITING_FOR_HUMAN:
            return run
        self._require_status(
            run,
            {RunStatus.RUNNING},
            RunStatus.WAITING_FOR_HUMAN,
        )
        run.prompt_recommendation = cast(dict[str, object], data.prompt_recommendation)
        run.provider_parameters = self._preserve_resume_reconciliations(
            run,
            data.provider_parameters,
        )
        run.latency_ms = data.latency_ms
        run.status = RunStatus.WAITING_FOR_HUMAN
        run.error_code = None
        await self._flush(run)
        return run

    async def mark_completed(
        self,
        run_id: UUID,
        data: GenerationRunComplete,
    ) -> GenerationRun:
        """Persist a validated recommendation and complete the run."""
        run = await self._require(run_id)
        if run.status is RunStatus.COMPLETED:
            return run
        self._require_status(run, {RunStatus.RUNNING}, RunStatus.COMPLETED)
        run.prompt_recommendation = cast(dict[str, object], data.prompt_recommendation)
        run.provider_parameters = self._preserve_resume_reconciliations(
            run,
            data.provider_parameters,
        )
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
        if run.status is RunStatus.FAILED and run.error_code == data.error_code:
            return run
        self._require_status(
            run,
            {RunStatus.PENDING, RunStatus.RUNNING, RunStatus.WAITING_FOR_HUMAN},
            RunStatus.FAILED,
        )
        run.status = RunStatus.FAILED
        run.error_code = data.error_code
        run.latency_ms = data.latency_ms
        if data.prompt_recommendation is not None:
            run.prompt_recommendation = cast(
                dict[str, object],
                data.prompt_recommendation,
            )
        if data.provider_parameters is not None:
            run.provider_parameters = self._preserve_resume_reconciliations(
                run,
                data.provider_parameters,
            )
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

    @staticmethod
    def _preserve_resume_reconciliations(
        run: GenerationRun,
        parameters: Mapping[str, object],
    ) -> dict[str, object]:
        """Keep bounded reconciliation audit history across workflow writes."""
        merged = dict(parameters)
        history = run.provider_parameters.get("resume_reconciliations")
        if isinstance(history, list):
            merged["resume_reconciliations"] = history
        return merged
