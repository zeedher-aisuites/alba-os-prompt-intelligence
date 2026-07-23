"""Service metadata and health routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.schemas.health import (
    DatabaseHealthResponse,
    ErrorResponse,
    HealthResponse,
    ServiceInfo,
)
from app.core.config import Settings, get_settings
from app.db.session import DatabaseDependency
from app.main_metadata import APP_VERSION

router = APIRouter(tags=["system"])
SettingsDependency = Annotated[Settings, Depends(get_settings)]


@router.get("/", response_model=ServiceInfo)
async def service_info(settings: SettingsDependency) -> ServiceInfo:
    """Return public service metadata."""
    return ServiceInfo(name=settings.app_name, version=APP_VERSION)


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDependency) -> HealthResponse:
    """Report process-level liveness without checking dependencies."""
    return HealthResponse(service=settings.app_name, environment=settings.environment)


@router.get(
    "/health/database",
    response_model=DatabaseHealthResponse,
    responses={503: {"model": ErrorResponse}},
)
async def database_health(database: DatabaseDependency) -> DatabaseHealthResponse:
    """Report whether PostgreSQL accepts a minimal query."""
    await database.check_connection()
    return DatabaseHealthResponse()
