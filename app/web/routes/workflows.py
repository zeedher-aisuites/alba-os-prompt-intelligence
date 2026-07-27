"""Server-rendered workflow creation, history, detail, and human-review routes."""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.core.exceptions import AlbaError
from app.domain.enums import QueryType, RunStatus
from app.web.dependencies import WebWorkflowServiceDependency
from app.web.filters import WorkflowFiltersDependency, filters_for_template
from app.web.pagination import pagination_navigation
from app.web.routes.pages import is_htmx
from app.web.schemas import WorkflowResumeInput, WorkflowStartInput

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/workflows/new", response_class=HTMLResponse)
async def workflow_new(request: Request, service: WebWorkflowServiceDependency) -> HTMLResponse:
    """Render an explicit workflow form with safe visible limits."""
    return await _workflow_form_response(request, service)


@router.post("/workflows", response_class=HTMLResponse)
async def workflow_create(request: Request, service: WebWorkflowServiceDependency) -> Response:
    """Validate, deduplicate, and start a durable workflow from an HTML form."""
    raw_values = await _form_values(request)
    try:
        payload = WorkflowStartInput.model_validate(raw_values)
    except ValidationError as exc:
        return await _workflow_form_response(
            request,
            service,
            values=raw_values,
            errors=_field_errors(exc),
            status_code=422,
        )
    result = await service.start_workflow(payload)
    return RedirectResponse(url=f"/workflows/{result.workflow.thread_id}", status_code=303)


@router.get("/workflows", response_class=HTMLResponse)
async def workflow_list(
    request: Request,
    service: WebWorkflowServiceDependency,
    filters: WorkflowFiltersDependency,
) -> Response:
    """Render simple persisted workflow history without semantic search."""
    workflows = await service.list_workflows(
        project_id=filters.project_id,
        status=filters.status,
        workflow_outcome=filters.outcome,
        provider=filters.provider,
        waiting_for_human=filters.waiting,
        offset=filters.offset,
        limit=filters.limit,
    )
    projects = await service.list_projects()
    template_name = "workflows/_list.html" if is_htmx(request) else "workflows/list.html"
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "workflows": workflows,
            "workflow_items": workflows.items,
            "projects": projects,
            "statuses": list(RunStatus),
            "filters": filters_for_template(filters),
            "pagination_navigation": pagination_navigation(
                "/workflows",
                filters,
                workflows.pagination,
                item_count=len(workflows.items),
            ),
            "clear_url": "/workflows",
        },
    )


@router.get("/workflows/{thread_id}", response_class=HTMLResponse)
async def workflow_detail(
    request: Request,
    thread_id: str,
    service: WebWorkflowServiceDependency,
) -> Response:
    """Render one workflow from PostgreSQL and its durable checkpoint."""
    workflow = await service.get_workflow(thread_id)
    return templates.TemplateResponse(
        request=request,
        name="workflows/detail.html",
        context={"workflow": workflow},
    )


@router.post("/workflows/{thread_id}/resume", response_class=HTMLResponse)
async def workflow_resume(
    request: Request,
    thread_id: str,
    service: WebWorkflowServiceDependency,
) -> Response:
    """Pass a closed human decision to the existing durable resume implementation."""
    raw_values = await _resume_form_values(request)
    try:
        command = WorkflowResumeInput.model_validate(raw_values)
    except ValidationError as exc:
        return await _resume_error_response(
            request,
            service,
            thread_id,
            _field_error_summary(exc),
            422,
        )
    try:
        workflow = await service.resume_workflow(thread_id, command)
    except AlbaError as exc:
        if is_htmx(request):
            return await _resume_error_response(
                request,
                service,
                thread_id,
                exc.detail.message,
                409,
            )
        raise
    if is_htmx(request):
        return templates.TemplateResponse(
            request=request,
            name="workflows/_workflow_card.html",
            context={"workflow": workflow},
        )
    return RedirectResponse(url=f"/workflows/{workflow.thread_id}", status_code=303)


@router.post("/workflows/{thread_id}/reconcile", response_class=HTMLResponse)
async def workflow_reconcile(
    request: Request,
    thread_id: str,
    service: WebWorkflowServiceDependency,
) -> Response:
    """Run only the existing narrow reconciliation for a documented legacy split state."""
    workflow = await service.reconcile_workflow(thread_id)
    if is_htmx(request):
        return templates.TemplateResponse(
            request=request,
            name="workflows/_workflow_card.html",
            context={"workflow": workflow},
        )
    return RedirectResponse(url=f"/workflows/{workflow.thread_id}", status_code=303)


@router.get("/workflows/partials/constraint", response_class=HTMLResponse)
async def constraint_input(request: Request) -> HTMLResponse:
    """Return an additional normal form input, requested progressively by HTMX."""
    return templates.TemplateResponse(
        request=request,
        name="workflows/_constraint_input.html",
        context={},
    )


async def _workflow_form_response(
    request: Request,
    service: WebWorkflowServiceDependency,
    *,
    values: Mapping[str, object] | None = None,
    errors: Mapping[str, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    projects = await service.list_projects()
    return templates.TemplateResponse(
        request=request,
        name="workflows/new.html",
        context={
            "projects": projects,
            "query_types": list(QueryType),
            "values": values or _empty_form_values(),
            "errors": errors or {},
        },
        status_code=status_code,
    )


async def _form_values(request: Request) -> dict[str, object]:
    form = await request.form()
    constraints = [str(value) for value in form.getlist("constraints") if str(value).strip()]
    return {
        "project_id": form.get("project_id", ""),
        "query_type": form.get("query_type", ""),
        "brief": form.get("brief", ""),
        "target_platform": _blank_to_none(form.get("target_platform")),
        "generation_method": _blank_to_none(form.get("generation_method")),
        "constraints": constraints,
        "provider": form.get("provider", "fake"),
        "thread_id": _blank_to_none(form.get("thread_id")),
    }


async def _resume_form_values(request: Request) -> dict[str, object]:
    form = await request.form()
    return {
        "decision": form.get("decision", ""),
        "feedback": _blank_to_none(form.get("feedback")),
    }


def _empty_form_values() -> dict[str, object]:
    return {
        "project_id": "",
        "query_type": "",
        "brief": "",
        "target_platform": "",
        "generation_method": "",
        "constraints": [""],
        "provider": "fake",
        "thread_id": "",
    }


def _field_errors(error: ValidationError) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in error.errors():
        location = item.get("loc", ())
        field = str(location[0]) if location else "form"
        values.setdefault(field, str(item["msg"]))
    return values


def _field_error_summary(error: ValidationError) -> str:
    return next(iter(_field_errors(error).values()), "The decision form is invalid.")


async def _resume_error_response(
    request: Request,
    service: WebWorkflowServiceDependency,
    thread_id: str,
    message: str,
    status_code: int,
) -> HTMLResponse:
    workflow = await service.get_workflow(thread_id)
    if not is_htmx(request):
        return templates.TemplateResponse(
            request=request,
            name="workflows/detail.html",
            context={"workflow": workflow, "resume_error": message},
            status_code=status_code,
        )
    return templates.TemplateResponse(
        request=request,
        name="workflows/_workflow_card.html",
        context={"workflow": workflow, "resume_error": message},
        status_code=status_code,
    )


def _blank_to_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
