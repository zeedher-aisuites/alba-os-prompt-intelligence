"""Shared application facade for local HTML and JSON workflow delivery."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Literal, cast
from uuid import UUID, uuid4

from psycopg import Error as PsycopgError
from pydantic import TypeAdapter

from app.core.config import Settings
from app.db.repositories import GenerationRunRepository, ProjectRepository, PromptExampleRepository
from app.db.session import Database
from app.domain.enums import GenerationStatus, QueryType, RunStatus
from app.domain.exceptions import EntityNotFoundError
from app.domain.schemas import GenerationRunRead, ProjectRead, PromptExampleRead
from app.recommendation.factory import RecommendationProviderKind
from app.recommendation.schemas import RecommendationRequest
from app.web.errors import WebDependencyUnavailableError
from app.web.library_facets import (
    enum_label,
    generation_method_label,
    platform_label,
)
from app.web.presenters import (
    present_project,
    present_prompt_example_detail,
    present_prompt_example_list_item,
    present_workflow,
    present_workflow_list_item,
)
from app.web.readiness import ReadinessCache
from app.web.schemas import (
    FilterOptionView,
    LibraryFilterOptionsView,
    PaginationView,
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
from app.workflow.checkpoint import open_workflow_checkpointer
from app.workflow.exceptions import (
    WorkflowAlreadyExistsError,
    WorkflowCheckpointUnavailableError,
    WorkflowStateError,
)
from app.workflow.factory import create_workflow_service
from app.workflow.schemas import ThreadId, WorkflowResumeCommand
from app.workflow.service import RecommendationWorkflowService

MAX_PAGE_SIZE = 50


class WebWorkflowApplicationService:
    """Thin facade sharing durable application behavior across HTTP representations."""

    def __init__(
        self,
        settings: Settings,
        database: Database,
        readiness_cache: ReadinessCache,
    ) -> None:
        self._settings = settings
        self._database = database
        self._readiness_cache = readiness_cache

    async def list_projects(self) -> list[ProjectOptionView]:
        """Return selectable projects as explicit read models."""
        async with self._database.transaction() as session:
            projects = await ProjectRepository(session).list(limit=MAX_PAGE_SIZE)
        return [present_project(ProjectRead.model_validate(project)) for project in projects]

    async def get_library_filter_options(
        self,
        *,
        project_id: UUID | None = None,
    ) -> LibraryFilterOptionsView:
        """Return explicit, bounded facet options without sending ORM rows to a template."""
        async with self._database.transaction() as session:
            projects = await ProjectRepository(session).list(limit=MAX_PAGE_SIZE)
            facets = await PromptExampleRepository(session).list_library_facet_values(
                project_id=project_id
            )
        return LibraryFilterOptionsView(
            projects=[present_project(ProjectRead.model_validate(project)) for project in projects],
            query_types=[
                FilterOptionView(value=item.value, label=enum_label(item.value))
                for item in QueryType
            ],
            statuses=[
                FilterOptionView(value=item.value, label=enum_label(item.value))
                for item in GenerationStatus
            ],
            platforms=[
                FilterOptionView(value=value, label=platform_label(value))
                for value in facets.platforms
            ],
            generation_methods=[
                FilterOptionView(value=value, label=generation_method_label(value))
                for value in facets.generation_methods
            ],
            tags=[FilterOptionView(value=value, label=value) for value in facets.tags],
        )

    async def list_recent_workflows(self, *, limit: int = 8) -> WorkflowListView:
        """Return a small dashboard history using persisted business runs only."""
        return await self.list_workflows(limit=limit)

    async def list_workflows(
        self,
        *,
        project_id: UUID | None = None,
        status: RunStatus | None = None,
        workflow_outcome: str | None = None,
        provider: Literal["fake", "ollama"] | None = None,
        waiting_for_human: bool | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> WorkflowListView:
        """List workflows with bounded pagination and no checkpoint-table access."""
        safe_limit = min(max(1, limit), MAX_PAGE_SIZE)
        safe_offset = max(0, offset)
        async with self._database.transaction() as session:
            runs = await GenerationRunRepository(session).list_workflows(
                project_id=project_id,
                status=status,
                provider=provider,
                workflow_outcome=workflow_outcome,
                waiting_for_human=waiting_for_human,
                offset=safe_offset,
                limit=safe_limit + 1,
            )
            projects = await ProjectRepository(session).list_by_ids(
                {run.project_id for run in runs}
            )
        project_map = {item.id: ProjectRead.model_validate(item) for item in projects}
        page_runs = runs[:safe_limit]
        items = [
            present_workflow_list_item(
                GenerationRunRead.model_validate(run),
                project_map[run.project_id],
            )
            for run in page_runs
            if run.project_id in project_map and run.workflow_thread_id is not None
        ]
        return WorkflowListView(
            items=items,
            pagination=PaginationView(
                offset=safe_offset,
                limit=safe_limit,
                has_more=len(runs) > safe_limit,
            ),
        )

    async def start_workflow(self, data: WorkflowStartInput) -> WorkflowStartResultView:
        """Start one workflow or return its equivalent pre-existing durable thread."""
        await self._require_provider_ready(data.provider)
        thread_id = data.thread_id or uuid4().hex
        request = RecommendationRequest(
            project_id=data.project_id,
            brief=data.brief,
            query_type=data.query_type,
            target_platform=data.target_platform,
            generation_method=data.generation_method,
            constraints=data.constraints,
        )
        try:
            async with self._workflow_service(data.provider) as service:
                await service.start(request, thread_id=thread_id)
        except WorkflowAlreadyExistsError:
            existing = await self.get_workflow(thread_id)
            if self._is_equivalent_start(existing, data):
                return WorkflowStartResultView(workflow=existing, created=False)
            raise
        return WorkflowStartResultView(
            workflow=await self.get_workflow(thread_id),
            created=True,
        )

    async def get_workflow(self, thread_id: str) -> WorkflowDetailView:
        """Rebuild a workflow page from the durable checkpoint and business run."""
        normalized_thread_id = _normalize_thread_id(thread_id)
        run = await self._run_by_thread(normalized_thread_id)
        async with self._workflow_service(_provider_kind(run.provider)) as service:
            result = await service.status(normalized_thread_id)
        project = await self._project_by_id(run.project_id)
        return present_workflow(result, run, project)

    async def resume_workflow(
        self,
        thread_id: str,
        command: WorkflowResumeInput,
    ) -> WorkflowDetailView:
        """Delegate an approved human command to the existing durable workflow service."""
        normalized_thread_id = _normalize_thread_id(thread_id)
        run = await self._run_by_thread(normalized_thread_id)
        await self._require_provider_ready(_provider_kind(run.provider))
        async with self._workflow_service(_provider_kind(run.provider)) as service:
            await service.resume(
                normalized_thread_id,
                WorkflowResumeCommand(decision=command.decision, feedback=command.feedback),
            )
        return await self.get_workflow(normalized_thread_id)

    async def reconcile_workflow(self, thread_id: str) -> WorkflowDetailView:
        """Expose the existing narrow legacy-resume reconciliation through the facade."""
        normalized_thread_id = _normalize_thread_id(thread_id)
        run = await self._run_by_thread(normalized_thread_id)
        async with self._workflow_service(_provider_kind(run.provider)) as service:
            await service.reconcile_unaccepted_resume(normalized_thread_id)
        return await self.get_workflow(normalized_thread_id)

    async def list_prompt_examples(
        self,
        *,
        project_id: UUID | None = None,
        query_type: QueryType | None = None,
        status: GenerationStatus | None = None,
        target_platform: str | None = None,
        generation_method: str | None = None,
        tag: str | None = None,
        text_query: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> PromptExampleListView:
        """List the corpus in read-only mode without embedding or retrieval work."""
        safe_limit = min(max(1, limit), MAX_PAGE_SIZE)
        safe_offset = max(0, offset)
        async with self._database.transaction() as session:
            examples = await PromptExampleRepository(session).list_for_library(
                project_id=project_id,
                query_type=query_type,
                status=status,
                target_platform=target_platform,
                generation_method=generation_method,
                tag=tag,
                text_query=text_query,
                offset=safe_offset,
                limit=safe_limit + 1,
            )
            projects = await ProjectRepository(session).list_by_ids(
                {example.project_id for example in examples}
            )
        project_map = {item.id: ProjectRead.model_validate(item) for item in projects}
        page_examples = examples[:safe_limit]
        return PromptExampleListView(
            items=[
                present_prompt_example_list_item(
                    PromptExampleRead.model_validate(example),
                    project_map[example.project_id],
                )
                for example in page_examples
                if example.project_id in project_map
            ],
            pagination=PaginationView(
                offset=safe_offset,
                limit=safe_limit,
                has_more=len(examples) > safe_limit,
            ),
        )

    async def get_prompt_example(self, example_id: UUID) -> PromptExampleDetailView:
        """Return one corpus example as an explicit safe read model."""
        async with self._database.transaction() as session:
            example = await PromptExampleRepository(session).get_by_id(example_id)
            if example is None:
                raise EntityNotFoundError("PromptExample", example_id)
            project = await ProjectRepository(session).get_by_id(example.project_id)
            if project is None:
                raise EntityNotFoundError("Project", example.project_id)
            return present_prompt_example_detail(
                PromptExampleRead.model_validate(example),
                ProjectRead.model_validate(project),
            )

    async def get_readiness(self) -> ReadinessView:
        """Return the brief cached readiness projection used by dashboard and API."""
        return await self._readiness_cache.get(self._settings, self._database)

    async def _require_provider_ready(self, provider: Literal["fake", "ollama"]) -> None:
        readiness = await self.get_readiness()
        availability = {item.name: item.available for item in readiness.dependencies}
        if not availability.get("PostgreSQL", False):
            raise WebDependencyUnavailableError("PostgreSQL")
        if not availability.get("Workflow checkpoints", False):
            raise WebDependencyUnavailableError("workflow checkpoints")
        if provider == "ollama" and not availability.get("EmbeddingGemma", False):
            raise WebDependencyUnavailableError("EmbeddingGemma")
        if provider == "ollama" and not availability.get("Qwen", False):
            raise WebDependencyUnavailableError("Qwen")

    async def _run_by_thread(self, thread_id: str) -> GenerationRunRead:
        async with self._database.transaction() as session:
            run = await GenerationRunRepository(session).get_by_workflow_thread_id(thread_id)
        if run is None:
            raise EntityNotFoundError("Workflow", thread_id)
        return GenerationRunRead.model_validate(run)

    async def _project_by_id(self, project_id: UUID) -> ProjectRead:
        async with self._database.transaction() as session:
            project = await ProjectRepository(session).get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project", project_id)
        return ProjectRead.model_validate(project)

    @asynccontextmanager
    async def _workflow_service(
        self,
        provider: RecommendationProviderKind,
    ) -> AsyncGenerator[RecommendationWorkflowService]:
        """Open a saver only for one workflow request; no checkpoint stays open at rest."""
        try:
            async with open_workflow_checkpointer(
                self._settings,
                database_url=self._database.database_url,
            ) as checkpointer:
                yield create_workflow_service(
                    self._settings,
                    self._database,
                    checkpointer,
                    provider_kind=provider,
                )
        except PsycopgError as exc:
            raise WorkflowCheckpointUnavailableError from exc

    @staticmethod
    def _is_equivalent_start(existing: WorkflowDetailView, incoming: WorkflowStartInput) -> bool:
        """Only redirect a duplicate browser submit when its business intent matches."""
        return (
            existing.project.id == incoming.project_id
            and existing.brief == incoming.brief
            and existing.provider == incoming.provider
            and existing.query_type is incoming.query_type
        )


def _provider_kind(value: str) -> RecommendationProviderKind:
    if value in {"fake", "ollama"}:
        return cast(RecommendationProviderKind, value)
    raise WorkflowStateError("The persisted workflow provider is not supported.")


def _normalize_thread_id(value: str) -> str:
    return cast(str, TypeAdapter(ThreadId).validate_python(value))
