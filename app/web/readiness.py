"""Lightweight dependency readiness probes for the local web interface."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import Error as PsycopgError
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.db.session import Database
from app.domain.exceptions import DatabaseUnavailableError
from app.web.schemas import DependencyStatusView, ReadinessView
from app.workflow.checkpoint import CHECKPOINT_SCHEMA, checkpoint_config, open_workflow_checkpointer

CHECKPOINT_TABLES = (
    "checkpoint_migrations",
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
)

logger = logging.getLogger(__name__)


class ReadinessCache:
    """A tiny non-authoritative cache that prevents an Ollama call per render."""

    def __init__(self, *, ttl_seconds: float = 3.0) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._value: ReadinessView | None = None
        self._checked_at: datetime | None = None
        self._lock = asyncio.Lock()

    async def get(self, settings: Settings, database: Database) -> ReadinessView:
        """Return a recent probe result or refresh it with short independent checks."""
        now = datetime.now(UTC)
        if (
            self._value is not None
            and self._checked_at is not None
            and now - self._checked_at < self._ttl
        ):
            return self._value
        async with self._lock:
            now = datetime.now(UTC)
            if (
                self._value is not None
                and self._checked_at is not None
                and now - self._checked_at < self._ttl
            ):
                return self._value
            self._value = await build_readiness(settings, database)
            self._checked_at = now
            return self._value


async def build_readiness(settings: Settings, database: Database) -> ReadinessView:
    """Probe dependencies without inference, checkpointer setup, or state mutation."""
    database_status = await _database_status(database)
    migration_status = await _migration_status(database)
    checkpoint_status = await _checkpoint_status(settings, database)
    ollama_statuses = await _ollama_statuses(settings)
    dependencies = [database_status, migration_status, checkpoint_status, *ollama_statuses]
    return ReadinessView(
        ready=all(item.available for item in dependencies),
        checked_at=datetime.now(UTC).isoformat(),
        dependencies=dependencies,
    )


async def _database_status(database: Database) -> DependencyStatusView:
    try:
        await database.check_connection()
    except DatabaseUnavailableError:
        return DependencyStatusView(
            name="PostgreSQL",
            available=False,
            detail="unavailable",
        )
    return DependencyStatusView(name="PostgreSQL", available=True, detail="reachable")


async def _migration_status(database: Database) -> DependencyStatusView:
    expected_head = _expected_alembic_head()
    try:
        async with database.engine.connect() as connection:
            current = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    except SQLAlchemyError:
        return DependencyStatusView(
            name="Alembic",
            available=False,
            detail="version table unavailable",
        )
    if current == expected_head:
        return DependencyStatusView(name="Alembic", available=True, detail="up to date")
    return DependencyStatusView(name="Alembic", available=False, detail="migration required")


async def _checkpoint_status(settings: Settings, database: Database) -> DependencyStatusView:
    """Probe the exact request-scoped saver used by the workflow facade.

    The structural table check makes a missing Stage 4 schema actionable, while
    opening the saver and reading a non-existent probe thread verifies the actual
    Psycopg DSN, schema search path, serializer, and lifecycle used at runtime.
    """
    try:
        async with database.engine.connect() as connection:
            schema_exists = await connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.schemata "
                    "WHERE schema_name = :schema)"
                ),
                {"schema": CHECKPOINT_SCHEMA},
            )
            tables = [
                await connection.scalar(
                    text("SELECT to_regclass(:table_name)"),
                    {
                        "table_name": f"{CHECKPOINT_SCHEMA}.{table}",
                    },
                )
                for table in CHECKPOINT_TABLES
            ]
    except SQLAlchemyError:
        return DependencyStatusView(
            name="Workflow checkpoints",
            available=False,
            detail="unavailable",
        )
    if schema_exists is not True or not all(table is not None for table in tables):
        return DependencyStatusView(
            name="Workflow checkpoints",
            available=False,
            detail="setup required",
        )

    try:
        async with open_workflow_checkpointer(
            settings,
            database_url=database.database_url,
        ) as checkpointer:
            await checkpointer.aget_tuple(checkpoint_config("__alba_readiness_probe__"))
    except (OSError, PsycopgError) as exc:
        if settings.workflow_diagnostics:
            logger.exception(
                "Workflow checkpoint readiness probe failed (%s) on %s.",
                type(exc).__name__,
                type(asyncio.get_running_loop()).__name__,
            )
        return DependencyStatusView(
            name="Workflow checkpoints",
            available=False,
            detail="unavailable",
        )
    return DependencyStatusView(name="Workflow checkpoints", available=True, detail="ready")


async def _ollama_statuses(settings: Settings) -> list[DependencyStatusView]:
    base_url = settings.ollama_base_url.unicode_string().rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{base_url}/api/tags")
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return [
            DependencyStatusView(name="Ollama", available=False, detail="unavailable"),
            DependencyStatusView(
                name="EmbeddingGemma",
                available=False,
                detail="Ollama unavailable",
            ),
            DependencyStatusView(name="Qwen", available=False, detail="Ollama unavailable"),
        ]
    try:
        payload = TypeAdapter(dict[str, object]).validate_python(response.json())
        models = TypeAdapter(list[dict[str, object]]).validate_python(payload.get("models", []))
    except ValidationError:
        models = []
    names = {item.get("name") for item in models if isinstance(item.get("name"), str)}
    return [
        DependencyStatusView(name="Ollama", available=True, detail="reachable"),
        DependencyStatusView(
            name="EmbeddingGemma",
            available=settings.embedding_model in names,
            detail="available" if settings.embedding_model in names else "model missing",
        ),
        DependencyStatusView(
            name="Qwen",
            available=settings.recommendation_model in names,
            detail="available" if settings.recommendation_model in names else "model missing",
        ),
    ]


def _expected_alembic_head() -> str:
    """Read the repository migration head rather than hard-coding a revision."""
    repository_root = Path(__file__).resolve().parents[2]
    configuration = Config(str(repository_root / "alembic.ini"))
    configuration.set_main_option("script_location", str(repository_root / "app/db/migrations"))
    return ScriptDirectory.from_config(configuration).get_current_head() or ""
