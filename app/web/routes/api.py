"""Versioned JSON API backed by the same web application facade as HTML."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.web.dependencies import WebWorkflowServiceDependency
from app.web.filters import LibraryFiltersDependency, WorkflowFiltersDependency
from app.web.schemas import (
    LibraryFilterOptionsView,
    ProjectOptionView,
    PromptExampleDetailView,
    PromptExampleListView,
    ReadinessView,
    WorkflowDetailView,
    WorkflowListView,
    WorkflowResumeInput,
    WorkflowStartInput,
    WorkflowStartResultView,
)

router = APIRouter(prefix="/api/v1", tags=["web"])


@router.post("/workflows", response_model=WorkflowStartResultView, status_code=201)
async def create_workflow(
    payload: WorkflowStartInput,
    service: WebWorkflowServiceDependency,
) -> WorkflowStartResultView | JSONResponse:
    """Create a durable workflow through the same facade used by the HTML form."""
    result = await service.start_workflow(payload)
    if result.created:
        return result
    return JSONResponse(status_code=200, content=result.model_dump(mode="json"))


@router.get("/workflows/{thread_id}", response_model=WorkflowDetailView)
async def get_workflow(thread_id: str, service: WebWorkflowServiceDependency) -> WorkflowDetailView:
    """Read a workflow from the durable checkpoint and business run."""
    return await service.get_workflow(thread_id)


@router.post("/workflows/{thread_id}/resume", response_model=WorkflowDetailView)
async def resume_workflow(
    thread_id: str,
    payload: WorkflowResumeInput,
    service: WebWorkflowServiceDependency,
) -> WorkflowDetailView:
    """Apply one closed human decision with Stage 4 concurrency safeguards."""
    return await service.resume_workflow(thread_id, payload)


@router.get("/workflows", response_model=WorkflowListView)
async def list_workflows(
    service: WebWorkflowServiceDependency,
    filters: WorkflowFiltersDependency,
) -> WorkflowListView:
    """Return paginated persisted workflow history, not semantic retrieval."""
    return await service.list_workflows(
        project_id=filters.project_id,
        status=filters.status,
        workflow_outcome=filters.outcome,
        provider=filters.provider,
        waiting_for_human=filters.waiting,
        offset=filters.offset,
        limit=filters.limit,
    )


@router.get("/projects", response_model=list[ProjectOptionView])
async def list_projects(service: WebWorkflowServiceDependency) -> list[ProjectOptionView]:
    """List projects suitable for local workflow creation."""
    return await service.list_projects()


@router.get("/examples", response_model=PromptExampleListView)
async def list_examples(
    service: WebWorkflowServiceDependency,
    filters: LibraryFiltersDependency,
) -> PromptExampleListView:
    """Read the library without exposing vectors or accepting mutations."""
    return await service.list_prompt_examples(
        project_id=filters.project_id,
        query_type=filters.query_type,
        status=filters.status,
        target_platform=filters.platform,
        generation_method=filters.method,
        tag=filters.tag,
        text_query=filters.text,
        offset=filters.offset,
        limit=filters.limit,
    )


@router.get("/examples/filter-options", response_model=LibraryFilterOptionsView)
async def example_filter_options(
    service: WebWorkflowServiceDependency,
    project_id: UUID | None = None,
) -> LibraryFilterOptionsView:
    """List bounded dynamic library facets without exposing internal prompt metadata."""
    return await service.get_library_filter_options(project_id=project_id)


@router.get("/examples/{example_id}", response_model=PromptExampleDetailView)
async def get_example(
    example_id: UUID,
    service: WebWorkflowServiceDependency,
) -> PromptExampleDetailView:
    """Read a single safe prompt-library record."""
    return await service.get_prompt_example(example_id)


@router.get("/readiness", response_model=ReadinessView)
async def readiness(service: WebWorkflowServiceDependency) -> ReadinessView:
    """Report cached, non-inference readiness for local operators."""
    return await service.get_readiness()
