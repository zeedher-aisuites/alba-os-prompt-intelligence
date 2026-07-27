"""FastAPI dependencies for the local web delivery layer."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.db.session import Database, get_database
from app.web.readiness import ReadinessCache
from app.web.service import WebWorkflowApplicationService


def get_readiness_cache(request: Request) -> ReadinessCache:
    """Resolve the app-scoped, non-authoritative short readiness cache."""
    return cast(ReadinessCache, request.app.state.readiness_cache)


def get_web_workflow_service(
    settings: Annotated[Settings, Depends(get_settings)],
    database: Annotated[Database, Depends(get_database)],
    readiness_cache: Annotated[ReadinessCache, Depends(get_readiness_cache)],
) -> WebWorkflowApplicationService:
    """Build a stateless facade; workflow checkpointers stay request-scoped inside it."""
    return WebWorkflowApplicationService(settings, database, readiness_cache)


WebWorkflowServiceDependency = Annotated[
    WebWorkflowApplicationService,
    Depends(get_web_workflow_service),
]
