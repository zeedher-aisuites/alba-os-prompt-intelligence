"""Human review ORM table."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Numeric, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.db.models.enum_values import generation_status_values
from app.domain.enums import GenerationStatus

if TYPE_CHECKING:
    from app.db.models.prompt_example import PromptExample


class HumanReview(UUIDPrimaryKeyMixin, Base):
    """Human-scored evaluation attached to a prompt example."""

    __tablename__ = "human_reviews"
    __table_args__ = (
        CheckConstraint(
            """
            overall_score BETWEEN 0 AND 1
            AND prompt_adherence_score BETWEEN 0 AND 1
            AND identity_consistency_score BETWEEN 0 AND 1
            AND outfit_fidelity_score BETWEEN 0 AND 1
            AND composition_score BETWEEN 0 AND 1
            AND physical_coherence_score BETWEEN 0 AND 1
            AND continuity_score BETWEEN 0 AND 1
            """,
            name="score_ranges",
        ),
        Index("ix_human_reviews_final_status", "final_status"),
        Index("ix_human_reviews_created_at", "created_at"),
    )

    prompt_example_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("prompt_examples.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    overall_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    prompt_adherence_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    identity_consistency_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    outfit_fidelity_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    composition_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    physical_coherence_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    continuity_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    strengths: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    problems: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    recommendations: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    final_status: Mapped[GenerationStatus] = mapped_column(
        Enum(
            GenerationStatus,
            values_callable=generation_status_values,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="generation_status_values",
            length=16,
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    prompt_example: Mapped[PromptExample] = relationship(
        back_populates="human_reviews",
        lazy="raise",
    )
