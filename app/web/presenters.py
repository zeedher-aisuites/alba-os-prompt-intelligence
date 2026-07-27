"""Pure presenters that turn validated domain data into safe web view models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError

from app.domain.enums import QueryType, RunStatus
from app.domain.schemas import GenerationRunRead, ProjectRead, PromptExampleRead
from app.recommendation.schemas import EvidenceReference, PromptRecommendation
from app.web.schemas import (
    ConstraintView,
    CritiqueView,
    EvidenceView,
    ProjectOptionView,
    PromptExampleDetailView,
    PromptExampleListItemView,
    RecommendationView,
    WorkflowActionsView,
    WorkflowDetailView,
    WorkflowListItemView,
)
from app.workflow.schemas import (
    HumanDecision,
    RecommendationCritique,
    WorkflowPhase,
    WorkflowResult,
)


def present_project(project: ProjectRead) -> ProjectOptionView:
    """Project an immutable project read model for navigation."""
    return ProjectOptionView(
        id=project.id,
        name=project.name,
        slug=project.slug,
        description=project.description,
    )


def present_workflow(
    result: WorkflowResult,
    run: GenerationRunRead,
    project: ProjectRead,
) -> WorkflowDetailView:
    """Build one safe detail projection from workflow and business state."""
    recommendation = result.recommendation or _recommendation_from_run(run)
    parameters = run.provider_parameters
    approved, rejected = _evidence_from_parameters(parameters)
    if result.interrupt is not None:
        approved = [present_evidence(item) for item in result.interrupt.positive_evidence]
        rejected = _rejected_evidence(
            result.interrupt.failure_evidence,
            result.interrupt.failure_warnings,
        )
    constraints = _constraints(result, recommendation)
    critique = result.critique or _critique_from_parameters(parameters)
    query_type = _query_type(parameters, recommendation)
    phase = result.phase.value
    workflow_outcome = _optional_text(parameters.get("workflow_outcome"))
    has_terminal_decision = result.human_decision in {
        HumanDecision.APPROVE,
        HumanDecision.REJECT,
    }
    has_terminal_outcome = workflow_outcome in {
        HumanDecision.APPROVE.value,
        HumanDecision.REJECT.value,
    }
    can_resume = (
        result.phase is WorkflowPhase.WAITING_FOR_HUMAN
        and result.waiting_for_human
        and result.run_status is RunStatus.WAITING_FOR_HUMAN
        and not has_terminal_decision
        and not has_terminal_outcome
    )
    can_reconcile = (
        result.waiting_for_human
        and result.run_status is RunStatus.RUNNING
        and result.human_decision is None
    )
    return WorkflowDetailView(
        workflow_id=result.workflow_id,
        thread_id=result.thread_id,
        run_id=result.run_id,
        checkpoint_id=result.checkpoint_id,
        checkpoint_id_short=short_identifier(result.checkpoint_id),
        project=present_project(project),
        query_type=query_type,
        target_platform=_optional_text(parameters.get("target_platform")),
        generation_method=_optional_text(parameters.get("generation_method"))
        or run.generation_method,
        provider=run.provider,
        model=run.model,
        phase=phase,
        run_status=result.run_status,
        workflow_outcome=workflow_outcome,
        created_at=format_utc(run.created_at),
        completed_at=format_utc(run.completed_at) if run.completed_at is not None else None,
        brief=run.brief_text,
        constraints=constraints,
        recommendation=(
            present_recommendation(recommendation) if recommendation is not None else None
        ),
        approved_evidence=approved,
        rejected_evidence=rejected,
        critique=present_critique(critique) if critique is not None else None,
        revision_count=result.revision_count,
        human_decision=result.human_decision,
        human_feedback=result.human_feedback,
        waiting_for_human=result.waiting_for_human,
        error_code=result.error_code or run.error_code,
        actions=WorkflowActionsView(
            can_approve=can_resume,
            can_revise=can_resume and result.revision_count == 0,
            can_reject=can_resume,
            can_reconcile=can_reconcile,
        ),
    )


def present_workflow_list_item(
    run: GenerationRunRead,
    project: ProjectRead,
) -> WorkflowListItemView:
    """Project persisted history without opening a LangGraph checkpoint."""
    recommendation = _recommendation_from_run(run)
    parameters = run.provider_parameters
    phase = _optional_text(parameters.get("workflow_phase"))
    revision_count = parameters.get("revision_count", 0)
    return WorkflowListItemView(
        thread_id=run.workflow_thread_id or "",
        run_id=run.id,
        project=present_project(project),
        brief_summary=truncate_text(run.brief_text, 180),
        query_type=_query_type(parameters, recommendation),
        phase=phase,
        run_status=run.status,
        workflow_outcome=_optional_text(parameters.get("workflow_outcome")),
        confidence=recommendation.confidence if recommendation is not None else None,
        provider=run.provider,
        revision_count=revision_count if isinstance(revision_count, int) else 0,
        waiting_for_human=run.status is RunStatus.WAITING_FOR_HUMAN,
        created_at=format_utc(run.created_at),
    )


def present_evidence(item: EvidenceReference, *, warning: str | None = None) -> EvidenceView:
    """Show evidence metadata only; raw embeddings never cross this boundary."""
    return EvidenceView(
        example_id=item.example_id,
        short_id=short_identifier(str(item.example_id)) or "",
        status=item.status,
        query_type=item.query_type,
        similarity=item.similarity,
        summary=item.summary,
        rejection_reason=item.rejection_reason,
        warning=warning,
    )


def present_recommendation(value: PromptRecommendation) -> RecommendationView:
    """Present validated application-stamped recommendation content."""
    return RecommendationView(
        recommended_prompt=value.recommended_prompt,
        rationale=value.rationale,
        assumptions=value.assumptions,
        confidence=value.confidence,
        provider_confidence=value.provider_confidence,
        needs_human_review=value.needs_human_review,
        covered_constraint_ids=value.covered_constraint_ids,
        unmet_constraint_ids=value.unmet_constraint_ids,
        suggested_parameters=dict(value.suggested_parameters),
        negative_prompt=value.negative_prompt,
    )


def present_critique(value: RecommendationCritique) -> CritiqueView:
    """Present deterministic critic findings without changing their meaning."""
    return CritiqueView(
        passed=value.passed,
        hard_failures=value.hard_failures,
        review_reasons=value.review_reasons,
        warnings=value.warnings,
        recommended_route=value.recommended_route.value,
    )


def present_prompt_example_list_item(
    example: PromptExampleRead,
    project: ProjectRead,
) -> PromptExampleListItemView:
    """Present one read-only corpus row without vector content."""
    return PromptExampleListItemView(
        id=example.id,
        project=present_project(project),
        prompt_summary=truncate_text(example.base_prompt, 200),
        expected_result_summary=truncate_text(example.expected_result, 160),
        status=example.status,
        query_type=example.query_type,
        target_platform=example.target_platform,
        generation_method=example.generation_method,
        tags=example.tags,
        rejection_reason=example.rejection_reason,
        embedding_state=embedding_state(example),
        created_at=format_utc(example.created_at),
    )


def present_prompt_example_detail(
    example: PromptExampleRead,
    project: ProjectRead,
) -> PromptExampleDetailView:
    """Present safe full corpus metadata without an embedding vector."""
    return PromptExampleDetailView(
        id=example.id,
        project=present_project(project),
        base_prompt=example.base_prompt,
        expected_result=example.expected_result,
        generated_image_description=example.generated_image_description,
        status=example.status,
        query_type=example.query_type,
        review_notes=example.review_notes,
        rejection_reason=example.rejection_reason,
        tags=example.tags,
        target_platform=example.target_platform,
        generation_method=example.generation_method,
        embedding_provider=example.embedding_provider,
        embedding_model=example.embedding_model,
        embedded_at=format_utc(example.embedded_at) if example.embedded_at is not None else None,
        embedding_state=embedding_state(example),
        created_at=format_utc(example.created_at),
        updated_at=format_utc(example.updated_at),
    )


def embedding_state(example: PromptExampleRead) -> Literal["missing", "stale", "current"]:
    """Expose only non-vector embedding freshness metadata to readers."""
    if example.embedded_at is None:
        return "missing"
    if not all(
        (
            example.embedding_provider,
            example.embedding_model,
            example.embedding_source_hash,
        )
    ):
        return "stale"
    return "current"


def short_identifier(value: str | None) -> str | None:
    """Abbreviate identifiers only for display; links retain the full value."""
    if value is None:
        return None
    return value if len(value) <= 12 else f"{value[:8]}…{value[-4:]}"


def format_utc(value: datetime) -> str:
    """Format already-normalized UTC timestamps consistently for local readers."""
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def truncate_text(value: str, maximum: int) -> str:
    """Make list views legible without altering the stored source data."""
    compact = " ".join(value.split())
    return compact if len(compact) <= maximum else f"{compact[: maximum - 1].rstrip()}…"


def _recommendation_from_run(run: GenerationRunRead) -> PromptRecommendation | None:
    try:
        return PromptRecommendation.model_validate(run.prompt_recommendation)
    except ValidationError:
        return None


def _critique_from_parameters(parameters: dict[str, Any]) -> RecommendationCritique | None:
    value = parameters.get("critique")
    if not isinstance(value, dict):
        return None
    try:
        return RecommendationCritique.model_validate(value)
    except ValidationError:
        return None


def _constraints(
    result: WorkflowResult,
    recommendation: PromptRecommendation | None,
) -> list[ConstraintView]:
    if recommendation is not None:
        return [
            ConstraintView(constraint_id=item.constraint_id, text=item.text)
            for item in recommendation.constraints
        ]
    if result.interrupt is not None:
        return [
            ConstraintView(constraint_id=item.constraint_id, text=item.text)
            for item in result.interrupt.constraints
        ]
    return []


def _evidence_from_parameters(
    parameters: dict[str, Any],
) -> tuple[list[EvidenceView], list[EvidenceView]]:
    approved = _validated_evidence(parameters.get("positive_evidence"))
    rejected = _validated_evidence(parameters.get("failure_evidence"))
    warnings = parameters.get("failure_warnings", [])
    return [present_evidence(item) for item in approved], _rejected_evidence(rejected, warnings)


def _validated_evidence(value: object) -> list[EvidenceReference]:
    try:
        entries = TypeAdapter(list[object]).validate_python(value)
    except ValidationError:
        return []
    evidence: list[EvidenceReference] = []
    for item in entries:
        try:
            evidence.append(EvidenceReference.model_validate(item))
        except ValidationError:
            continue
    return evidence


def _rejected_evidence(
    items: list[EvidenceReference],
    warnings: object,
) -> list[EvidenceView]:
    warning_map: dict[str, str] = {}
    try:
        warning_entries = TypeAdapter(list[dict[str, str]]).validate_python(warnings)
    except ValidationError:
        warning_entries = []
    for item in warning_entries:
        evidence_id = item.get("evidence_id")
        warning = item.get("warning")
        if evidence_id is not None and warning is not None:
            warning_map[evidence_id] = warning
    return [present_evidence(item, warning=warning_map.get(str(item.example_id))) for item in items]


def _query_type(
    parameters: dict[str, Any],
    recommendation: PromptRecommendation | None,
) -> QueryType | None:
    value = parameters.get("query_type")
    if not isinstance(value, str) and recommendation is not None:
        candidate = recommendation.suggested_parameters.get("query_type")
        value = candidate if isinstance(candidate, str) else None
    try:
        return QueryType(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
