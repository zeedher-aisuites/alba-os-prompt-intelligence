"""Official PostgreSQL checkpointer construction and configuration."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import PostgresDsn
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.db.session import Database
from app.workflow.exceptions import WorkflowCheckpointSchemaMissingError

# The PostgreSQL schema provides application isolation. LangGraph reserves
# non-empty checkpoint namespaces for actual subgraph paths, so the root graph
# must use the empty namespace.
CHECKPOINT_NAMESPACE = ""
CHECKPOINT_SCHEMA = "alba_workflow_checkpoints"


def checkpoint_config(thread_id: str) -> RunnableConfig:
    """Return the stable durable cursor used for every graph operation."""
    return {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": CHECKPOINT_NAMESPACE,
        }
    }


def checkpoint_connection_string(
    database_url: PostgresDsn,
    *,
    schema: str,
) -> str:
    """Convert the application asyncpg URL into a private Psycopg URL."""
    url = make_url(database_url.unicode_string()).set(drivername="postgresql")
    url = url.update_query_dict(
        {
            "options": f"-csearch_path={schema},public",
        }
    )
    return url.render_as_string(hide_password=False)


@asynccontextmanager
async def open_workflow_checkpointer(
    settings: Settings,
    *,
    database_url: PostgresDsn | None = None,
) -> AsyncGenerator[AsyncPostgresSaver]:
    """Open the official saver with strict, non-pickle serialization."""
    resolved_url = database_url or settings.database_url.get_secret_value()
    connection_string = checkpoint_connection_string(
        resolved_url,
        schema=CHECKPOINT_SCHEMA,
    )
    serializer = JsonPlusSerializer(
        pickle_fallback=False,
        allowed_msgpack_modules=(),
    )
    async with AsyncPostgresSaver.from_conn_string(
        connection_string,
        serde=serializer,
    ) as checkpointer:
        yield checkpointer


async def setup_workflow_checkpointer(
    checkpointer: AsyncPostgresSaver,
    database: Database,
) -> None:
    """Run the official idempotent checkpointer migrations explicitly."""
    async with database.engine.connect() as connection:
        schema_exists = await connection.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.schemata
                    WHERE schema_name = :schema
                )
                """
            ),
            {"schema": CHECKPOINT_SCHEMA},
        )
    if schema_exists is not True:
        raise WorkflowCheckpointSchemaMissingError()
    await checkpointer.setup()
