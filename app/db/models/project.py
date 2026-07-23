"""Project ORM table."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.generation_run import GenerationRun
    from app.db.models.prompt_example import PromptExample


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Top-level knowledge and generation context."""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("btrim(name) <> ''", name="name_not_empty"),
        CheckConstraint("btrim(slug) <> ''", name="slug_not_empty"),
        Index("ix_projects_name", "name"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    prompt_examples: Mapped[list[PromptExample]] = relationship(
        back_populates="project",
        lazy="raise",
        passive_deletes=True,
    )
    generation_runs: Mapped[list[GenerationRun]] = relationship(
        back_populates="project",
        lazy="raise",
        passive_deletes=True,
    )
