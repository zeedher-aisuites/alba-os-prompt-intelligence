"""Server-rendered dashboard and read-only prompt-library routes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AlbaError
from app.web.dependencies import WebWorkflowServiceDependency
from app.web.filters import LibraryFilters, LibraryFiltersDependency, filters_for_template
from app.web.pagination import page_url, pagination_navigation
from app.web.schemas import (
    LibraryFilterOptionsView,
    PaginationView,
    ReadinessView,
    WorkflowListView,
)

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/docs", response_class=HTMLResponse)
async def local_api_docs(request: Request) -> HTMLResponse:
    """Serve local Swagger UI assets that remain usable under the strict CSP."""
    return templates.TemplateResponse(request=request, name="docs.html", context={})


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, service: WebWorkflowServiceDependency) -> HTMLResponse:
    """Render the small local operational dashboard."""
    projects_result, workflows_result, readiness_result = await asyncio.gather(
        service.list_projects(),
        service.list_recent_workflows(),
        service.get_readiness(),
        return_exceptions=True,
    )
    project_error = isinstance(projects_result, (AlbaError, OSError, SQLAlchemyError))
    workflow_error = isinstance(workflows_result, (AlbaError, OSError, SQLAlchemyError))
    readiness_error = isinstance(readiness_result, (AlbaError, OSError, SQLAlchemyError))
    projects = [] if project_error else projects_result
    workflows = (
        WorkflowListView(
            items=[],
            pagination=PaginationView(offset=0, limit=8, has_more=False),
        )
        if workflow_error
        else workflows_result
    )
    readiness = (
        ReadinessView(
            ready=False,
            checked_at=datetime.now(UTC).isoformat(),
            dependencies=[],
        )
        if readiness_error
        else readiness_result
    )
    assert isinstance(projects, list)
    assert isinstance(workflows, WorkflowListView)
    assert isinstance(readiness, ReadinessView)
    waiting_count = sum(item.waiting_for_human for item in workflows.items)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "projects": projects,
            "workflows": workflows.items,
            "waiting_count": waiting_count,
            "readiness": readiness,
            "dependency_warning": project_error or workflow_error or readiness_error,
        },
    )


@router.get("/library", response_class=HTMLResponse)
async def library_list(
    request: Request,
    service: WebWorkflowServiceDependency,
    filters: LibraryFiltersDependency,
) -> HTMLResponse:
    """Render the read-only local prompt-experience library."""
    filter_options = await service.get_library_filter_options(project_id=filters.project_id)
    effective_filters = _compatible_library_filters(filters, filter_options)
    examples = await service.list_prompt_examples(
        project_id=effective_filters.project_id,
        query_type=effective_filters.query_type,
        status=effective_filters.status,
        target_platform=effective_filters.platform,
        generation_method=effective_filters.method,
        tag=effective_filters.tag,
        text_query=effective_filters.text,
        offset=effective_filters.offset,
        limit=effective_filters.limit,
    )
    template_name = "library/_content.html" if is_htmx(request) else "library/list.html"
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "examples": examples,
            "filter_options": filter_options,
            "filters": filters_for_template(effective_filters),
            "pagination_navigation": pagination_navigation(
                "/library",
                effective_filters,
                examples.pagination,
                item_count=len(examples.items),
            ),
            "library_return_url": page_url(
                "/library",
                effective_filters,
                offset=effective_filters.offset,
            ),
            "clear_url": "/library",
        },
    )


@router.get("/library/{example_id}", response_class=HTMLResponse)
async def library_detail(
    request: Request,
    example_id: UUID,
    service: WebWorkflowServiceDependency,
    return_to: str | None = Query(default=None, max_length=2000),
) -> HTMLResponse:
    """Render one safe, read-only prompt-example detail page."""
    example = await service.get_prompt_example(example_id)
    return templates.TemplateResponse(
        request=request,
        name="library/detail.html",
        context={"example": example, "return_url": _safe_library_return_url(return_to)},
    )


def is_htmx(request: Request) -> bool:
    """Detect an HTMX-enhanced request while preserving normal HTML behavior."""
    return request.headers.get("HX-Request", "").casefold() == "true"


def _safe_library_return_url(value: str | None) -> str:
    """Accept only local `/library` links, preserving their validated query string."""
    if not value:
        return "/library"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.path != "/library":
        return "/library"
    return urlunsplit(("", "", "/library", parsed.query, ""))


def _compatible_library_filters(
    filters: LibraryFilters,
    options: LibraryFilterOptionsView,
) -> LibraryFilters:
    """Clear dependent facets not available for a selected project."""
    if filters.project_id is None:
        return filters
    updates: dict[str, None] = {}
    for field, values in (
        ("platform", options.platforms),
        ("method", options.generation_methods),
        ("tag", options.tags),
    ):
        selected = getattr(filters, field)
        if selected is not None and selected not in {option.value for option in values}:
            updates[field] = None
    return filters.model_copy(update=updates) if updates else filters
