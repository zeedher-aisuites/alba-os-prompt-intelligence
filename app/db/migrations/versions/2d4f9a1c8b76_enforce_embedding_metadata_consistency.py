"""enforce embedding metadata consistency

Revision ID: 2d4f9a1c8b76
Revises: f15ea754ecc3
Create Date: 2026-07-23 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "2d4f9a1c8b76"
down_revision: str | Sequence[str] | None = "f15ea754ecc3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Require vector and provenance metadata to be absent or complete together."""
    # Alembic autogenerate does not reliably detect CHECK constraints. This
    # invariant is therefore expressed explicitly in the migration.
    op.create_check_constraint(
        op.f("ck_prompt_examples_embedding_metadata_consistent"),
        "prompt_examples",
        """
        (
            embedding IS NULL
            AND embedding_provider IS NULL
            AND embedding_model IS NULL
            AND embedding_source_hash IS NULL
            AND embedded_at IS NULL
        )
        OR
        (
            embedding IS NOT NULL
            AND embedding_provider IS NOT NULL
            AND embedding_model IS NOT NULL
            AND embedding_source_hash IS NOT NULL
            AND embedded_at IS NOT NULL
        )
        """,
    )


def downgrade() -> None:
    """Allow partial embedding metadata states again."""
    op.drop_constraint(
        op.f("ck_prompt_examples_embedding_metadata_consistent"),
        "prompt_examples",
        type_="check",
    )
