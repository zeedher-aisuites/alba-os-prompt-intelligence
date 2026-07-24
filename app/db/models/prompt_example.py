"""Prompt example ORM table."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.constants import EMBEDDING_DIMENSIONS
from app.db.models.enum_values import generation_status_values, query_type_values
from app.domain.enums import GenerationStatus, QueryType

if TYPE_CHECKING:
    from app.db.models.human_review import HumanReview
    from app.db.models.project import Project


class PromptExample(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Stored positive, pending, or rejected prompt knowledge."""

    __tablename__ = "prompt_examples"
    __table_args__ = (
        CheckConstraint("btrim(base_prompt) <> ''", name="base_prompt_not_empty"),
        CheckConstraint("btrim(expected_result) <> ''", name="expected_result_not_empty"),
        CheckConstraint("btrim(embedding_text) <> ''", name="embedding_text_not_empty"),
        CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1)",
            name="quality_score_range",
        ),
        CheckConstraint(
            "image_sha256 IS NULL OR char_length(image_sha256) = 64",
            name="image_sha256_length",
        ),
        CheckConstraint(
            """
            embedding_source_hash IS NULL
            OR embedding_source_hash ~ '^[0-9a-f]{64}$'
            """,
            name="embedding_source_hash_format",
        ),
        CheckConstraint(
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
            name="embedding_metadata_consistent",
        ),
        Index(
            "ix_prompt_examples_project_status_query_type",
            "project_id",
            "status",
            "query_type",
        ),
        Index("ix_prompt_examples_query_type", "query_type"),
        Index("ix_prompt_examples_status", "status"),
        Index("ix_prompt_examples_target_platform", "target_platform"),
        Index("ix_prompt_examples_created_at", "created_at"),
    )

    project_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    base_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    expected_result: Mapped[str] = mapped_column(Text, nullable=False)
    generated_image_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_method: Mapped[str] = mapped_column(String(100), nullable=False)
    target_platform: Mapped[str] = mapped_column(String(100), nullable=False)
    query_type: Mapped[QueryType] = mapped_column(
        Enum(
            QueryType,
            values_callable=query_type_values,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="query_type_values",
            length=32,
        ),
        nullable=False,
    )
    status: Mapped[GenerationStatus] = mapped_column(
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
        default=GenerationStatus.IN_REVIEW,
        server_default=GenerationStatus.IN_REVIEW.value,
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    image_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    embedding_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS),
        nullable=True,
    )
    embedding_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    project: Mapped[Project] = relationship(back_populates="prompt_examples", lazy="raise")
    human_reviews: Mapped[list[HumanReview]] = relationship(
        back_populates="prompt_example",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
