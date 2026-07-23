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
