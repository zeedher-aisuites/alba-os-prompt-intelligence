"""Generation run ORM table."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.db.models.enum_values import run_status_values
from app.domain.enums import RunStatus

if TYPE_CHECKING:
    from app.db.models.project import Project


class GenerationRun(UUIDPrimaryKeyMixin, Base):
    """Prepared persistence for future provider generation executions."""

    __tablename__ = "generation_runs"
    __table_args__ = (
        CheckConstraint("btrim(brief_text) <> ''", name="brief_text_not_empty"),
        CheckConstraint(
            "estimated_cost_usd IS NULL OR estimated_cost_usd >= 0",
            name="estimated_cost_non_negative",
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="latency_non_negative",
        ),
        Index(
            "ix_generation_runs_project_status_created_at",
            "project_id",
            "status",
            "created_at",
        ),
        Index("ix_generation_runs_status", "status"),
        Index("ix_generation_runs_created_at", "created_at"),
    )

    project_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    brief_text: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_recommendation: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    generation_method: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_parameters: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    status: Mapped[RunStatus] = mapped_column(
        Enum(
            RunStatus,
            values_callable=run_status_values,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="run_status_values",
            length=24,
        ),
        nullable=False,
        default=RunStatus.PENDING,
        server_default=RunStatus.PENDING.value,
    )
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="generation_runs", lazy="raise")
