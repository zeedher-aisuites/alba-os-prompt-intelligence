"""Schemas for service metadata and health responses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ServiceInfo(BaseModel):
    """Public service metadata."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    docs_url: str = "/docs"


class HealthResponse(BaseModel):
    """Process-level health response."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    service: str
    environment: str


class DatabaseHealthResponse(BaseModel):
    """PostgreSQL readiness response."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    database: Literal["reachable"] = "reachable"


class ErrorResponse(BaseModel):
    """Stable expected-error response."""

    model_config = ConfigDict(frozen=True)

    error_code: str
    message: str
    retryable: bool
    trace_id: str | None = None
