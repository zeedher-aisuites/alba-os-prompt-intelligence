"""Typed SQLAlchemy enum-value callbacks."""

from __future__ import annotations

from app.domain.enums import GenerationStatus, QueryType, RunStatus


def query_type_values(enum_type: type[QueryType]) -> list[str]:
    """Persist QueryType values rather than Python member names."""
    return [item.value for item in enum_type]


def generation_status_values(enum_type: type[GenerationStatus]) -> list[str]:
    """Persist GenerationStatus values rather than Python member names."""
    return [item.value for item in enum_type]


def run_status_values(enum_type: type[RunStatus]) -> list[str]:
    """Persist RunStatus values rather than Python member names."""
    return [item.value for item in enum_type]
