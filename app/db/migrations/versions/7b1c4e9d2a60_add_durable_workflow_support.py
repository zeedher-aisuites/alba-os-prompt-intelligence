"""add durable workflow support

Revision ID: 7b1c4e9d2a60
Revises: 2d4f9a1c8b76
Create Date: 2026-07-23 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b1c4e9d2a60"
down_revision: str | Sequence[str] | None = "2d4f9a1c8b76"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKPOINT_SCHEMA = "alba_workflow_checkpoints"


def upgrade() -> None:
    """Create an isolated checkpointer namespace and durable thread mapping."""
    # AsyncPostgresSaver.setup() owns its internal tables, but the namespace is
    # application architecture and therefore remains under Alembic control.
    op.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{CHECKPOINT_SCHEMA}"'))
    op.add_column(
        "generation_runs",
        sa.Column("workflow_thread_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ux_generation_runs_workflow_thread_id",
        "generation_runs",
        ["workflow_thread_id"],
        unique=True,
        postgresql_where=sa.text("workflow_thread_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove durable workflow metadata and every technical checkpoint."""
    op.drop_index(
        "ux_generation_runs_workflow_thread_id",
        table_name="generation_runs",
        postgresql_where=sa.text("workflow_thread_id IS NOT NULL"),
    )
    op.drop_column("generation_runs", "workflow_thread_id")
    # This schema is exclusive to Alba's LangGraph checkpointer. CASCADE is
    # intentional on downgrade because its tables contain derived runtime state.
    op.execute(sa.text(f'DROP SCHEMA IF EXISTS "{CHECKPOINT_SCHEMA}" CASCADE'))
