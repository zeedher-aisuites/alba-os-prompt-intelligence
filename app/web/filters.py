"""Shared, strict query-filter parsing for HTML and versioned JSON routes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import Depends, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ConfigDict, Field, ValidationError, field_validator, model_validator

from app.domain.enums import GenerationStatus, QueryType, RunStatus
from app.web.library_facets import (
    normalize_generation_method,
    normalize_platform,
    normalize_tag,
)
from app.web.schemas import WebModel


class BaseFilters(WebModel):
    """Normalize browser empty fields before strongly validating filter values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def normalize_query_values(cls, value: object) -> object:
        """Turn blank strings into absent optional filters and trim user input once."""
        if not isinstance(value, Mapping):
            return value
        mapping = cast(Mapping[object, object], value)
        normalized: dict[str, object] = {}
        for key, raw in mapping.items():
            if isinstance(raw, str):
                stripped = raw.strip()
                if not stripped and key in {"offset", "limit"}:
                    continue
                normalized[str(key)] = stripped or None
            else:
                normalized[str(key)] = raw
        for field in ("query_type", "status", "provider", "outcome"):
            candidate = normalized.get(field)
            if isinstance(candidate, str):
                normalized[field] = candidate.casefold()
        return normalized


class LibraryFilters(BaseFilters):
    """The complete shared filter contract for the read-only prompt library."""

    project_id: UUID | None = None
    query_type: QueryType | None = None
    status: GenerationStatus | None = None
    platform: str | None = Field(default=None, max_length=100)
    method: str | None = Field(default=None, max_length=100)
    tag: str | None = Field(default=None, max_length=80)
    text: str | None = Field(default=None, max_length=500)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=50)

    @field_validator("platform", mode="after")
    @classmethod
    def normalize_platform_value(cls, value: str | None) -> str | None:
        return normalize_platform(value) if value is not None else None

    @field_validator("method", mode="after")
    @classmethod
    def normalize_generation_method_value(cls, value: str | None) -> str | None:
        return normalize_generation_method(value) if value is not None else None

    @field_validator("tag", mode="after")
    @classmethod
    def normalize_tag_value(cls, value: str | None) -> str | None:
        return normalize_tag(value) if value is not None else None


class WorkflowFilters(BaseFilters):
    """The complete shared filter contract for persisted workflow history."""

    project_id: UUID | None = None
    status: RunStatus | None = None
    outcome: Literal["approve", "reject"] | None = None
    provider: Literal["fake", "ollama"] | None = None
    waiting: bool | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=50)


def _parse_filters[FilterModel: BaseFilters](
    model: type[FilterModel],
    request: Request,
) -> FilterModel:
    """Translate Pydantic input failures into FastAPI's safe 422 pathway."""
    try:
        return model.model_validate(dict(request.query_params))
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


def get_library_filters(request: Request) -> LibraryFilters:
    """Parse identical library filters for HTML and `/api/v1` requests."""
    return _parse_filters(LibraryFilters, request)


def get_workflow_filters(request: Request) -> WorkflowFilters:
    """Parse identical workflow-history filters for HTML and `/api/v1` requests."""
    return _parse_filters(WorkflowFilters, request)


LibraryFiltersDependency = Annotated[LibraryFilters, Depends(get_library_filters)]
WorkflowFiltersDependency = Annotated[WorkflowFilters, Depends(get_workflow_filters)]


def filters_for_template(filters: BaseFilters) -> dict[str, Any]:
    """Return canonical scalar values that Jinja can compare with form options."""
    values = filters.model_dump(mode="json")
    return {
        key: ("" if value is None else str(value).casefold() if isinstance(value, bool) else value)
        for key, value in values.items()
    }
