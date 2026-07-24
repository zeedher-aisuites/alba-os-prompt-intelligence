"""Application service for retrieval-backed structured prompt recommendations."""

from __future__ import annotations

from time import perf_counter
from uuid import UUID

from app.core.exceptions import AlbaError
from app.db.repositories import (
    GenerationRunRepository,
    ProjectRepository,
)
from app.db.session import Database
from app.domain.enums import RunStatus
from app.domain.exceptions import EntityNotFoundError
from app.domain.schemas import (
    GenerationRunComplete,
    GenerationRunCreate,
    GenerationRunFail,
    RetrievalQuery,
    RetrievedPromptExample,
)
from app.embeddings.protocol import EmbeddingProvider
from app.recommendation.context import RecommendationContextBuilder
from app.recommendation.exceptions import (
    ConstraintAccountingError,
    EvidenceStatusMismatchError,
    FabricatedConstraintReferenceError,
    FabricatedEvidenceReferenceError,
    MissingPositiveEvidenceCitationError,
    RecommendationError,
)
from app.recommendation.protocol import RecommendationProvider
from app.recommendation.schemas import (
    EvidenceReference,
    PromptRecommendation,
    RecommendationContext,
    RecommendationDraft,
    RecommendationRequest,
    RecommendationResult,
)
from app.retrieval.service import RetrievalService

UNGROUNDED_POSITIVE_CONFIDENCE_MAX = 0.35
UNMET_CONSTRAINT_CONFIDENCE_MAX = 0.50
MISSING_FAILURE_WARNING_CONFIDENCE_MAX = 0.50
NO_EVIDENCE_CONFIDENCE_MAX = 0.30
STRUCTURED_REPAIR_PENALTY = 0.10


class RecommendationService:
    """Coordinate one embedding, bounded retrieval, local generation, and persistence."""

    def __init__(
        self,
        database: Database,
        embedding_provider: EmbeddingProvider,
        recommendation_provider: RecommendationProvider,
        *,
        context_builder: RecommendationContextBuilder | None = None,
        maximum_retrieval_limit: int = 20,
    ) -> None:
        self._database = database
        self._embedding_provider = embedding_provider
        self._recommendation_provider = recommendation_provider
        self._context_builder = context_builder or RecommendationContextBuilder()
        self._maximum_retrieval_limit = maximum_retrieval_limit

    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        """Run one recommendation without holding PostgreSQL open during HTTP."""
        started = perf_counter()
        run_id = await self._start_run(request)
        try:
            retrieval_text = self._retrieval_text(request)
            query_vector = await self._embedding_provider.embed_query(retrieval_text)
            positive, failures = await self._retrieve(
                request,
                retrieval_text=retrieval_text,
                query_vector=query_vector,
            )
            context = self._context_builder.build(
                request,
                positive_evidence=positive,
                failure_evidence=failures,
            )
            repairs_before = self._recommendation_provider.repair_attempts_used
            draft = await self._recommendation_provider.generate_recommendation(
                context,
                validate=lambda candidate: validate_draft_grounding(
                    candidate,
                    context,
                    require_positive_citation=True,
                ),
            )
            repairs_used = self._recommendation_provider.repair_attempts_used - repairs_before
            recommendation = finalize_recommendation(
                draft,
                context,
                provider_name=self._recommendation_provider.provider_name,
                model_name=self._recommendation_provider.model_name,
                repair_attempts_used=repairs_used,
            )
            latency_ms = self._elapsed_ms(started)
            await self._complete_run(
                run_id,
                request=request,
                context=context,
                recommendation=recommendation,
                latency_ms=latency_ms,
            )
            return RecommendationResult(
                run_id=run_id,
                status=RunStatus.COMPLETED,
                recommendation=recommendation,
                positive_evidence=context.positive_evidence,
                failure_evidence=context.failure_evidence,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            await self._safe_fail_run(
                run_id,
                error_code=self._error_code(exc),
                latency_ms=self._elapsed_ms(started),
            )
            raise

    async def _start_run(self, request: RecommendationRequest) -> UUID:
        parameters = {
            "query_type": request.query_type.value,
            "target_platform": request.target_platform,
            "constraints": list(request.constraints),
            "positive_limit": request.positive_limit,
            "failure_limit": request.failure_limit,
            "minimum_similarity": request.minimum_similarity,
            "embedding_provider": self._embedding_provider.provider_name,
            "embedding_model": self._embedding_provider.model_name,
        }
        async with self._database.transaction() as session:
            project = await ProjectRepository(session).get_by_id(request.project_id)
            if project is None:
                raise EntityNotFoundError("Project", request.project_id)
            run = await GenerationRunRepository(session).create(
                GenerationRunCreate.model_validate(
                    {
                        "project_id": request.project_id,
                        "brief_text": request.brief,
                        "prompt_recommendation": {},
                        "provider": self._recommendation_provider.provider_name,
                        "model": self._recommendation_provider.model_name,
                        "generation_method": request.generation_method or "unspecified",
                        "provider_parameters": parameters,
                        "status": RunStatus.RUNNING,
                        "trace_id": request.trace_id,
                    }
                )
            )
            return run.id

    async def _retrieve(
        self,
        request: RecommendationRequest,
        *,
        retrieval_text: str,
        query_vector: list[float],
    ) -> tuple[list[EvidenceReference], list[EvidenceReference]]:
        query = RetrievalQuery(
            text=retrieval_text,
            project_id=request.project_id,
            query_type=request.query_type,
            target_platform=request.target_platform,
            minimum_similarity=request.minimum_similarity,
            limit=max(request.positive_limit, request.failure_limit),
        )
        async with self._database.transaction() as session:
            retrieval = RetrievalService(
                session,
                self._embedding_provider,
                maximum_limit=self._maximum_retrieval_limit,
            )
            positive = await retrieval.search_approved_examples_by_vector(
                query.model_copy(update={"limit": request.positive_limit}),
                query_vector,
            )
            failures = await retrieval.search_failure_patterns_by_vector(
                query.model_copy(update={"limit": request.failure_limit}),
                query_vector,
            )
        return (
            [self._evidence(item) for item in positive.items],
            [self._evidence(item) for item in failures.items],
        )

    @staticmethod
    def _evidence(item: RetrievedPromptExample) -> EvidenceReference:
        summary_parts = [
            f"Prompt: {item.base_prompt}",
            f"Expected result: {item.expected_result}",
        ]
        if item.review_notes:
            summary_parts.append(f"Review notes: {item.review_notes}")
        return EvidenceReference(
            example_id=item.id,
            status=item.status,
            query_type=item.query_type,
            similarity=item.similarity,
            summary="\n".join(summary_parts),
            rejection_reason=item.rejection_reason,
        )

    async def _complete_run(
        self,
        run_id: UUID,
        *,
        request: RecommendationRequest,
        context: RecommendationContext,
        recommendation: PromptRecommendation,
        latency_ms: int,
    ) -> None:
        parameters = {
            "query_type": request.query_type.value,
            "target_platform": request.target_platform,
            "constraints": [item.model_dump(mode="json") for item in context.constraints],
            "positive_limit": request.positive_limit,
            "failure_limit": request.failure_limit,
            "minimum_similarity": request.minimum_similarity,
            "embedding_provider": self._embedding_provider.provider_name,
            "embedding_model": self._embedding_provider.model_name,
            "positive_evidence": [
                item.model_dump(mode="json") for item in context.positive_evidence
            ],
            "failure_evidence": [item.model_dump(mode="json") for item in context.failure_evidence],
            "omitted_positive_evidence": context.omitted_positive_evidence,
            "omitted_failure_evidence": context.omitted_failure_evidence,
        }
        async with self._database.transaction() as session:
            await GenerationRunRepository(session).mark_completed(
                run_id,
                GenerationRunComplete.model_validate(
                    {
                        "prompt_recommendation": recommendation.model_dump(mode="json"),
                        "provider_parameters": parameters,
                        "latency_ms": latency_ms,
                    }
                ),
            )

    async def _safe_fail_run(
        self,
        run_id: UUID,
        *,
        error_code: str,
        latency_ms: int,
    ) -> None:
        try:
            async with self._database.transaction() as session:
                await GenerationRunRepository(session).mark_failed(
                    run_id,
                    GenerationRunFail(
                        error_code=error_code,
                        latency_ms=latency_ms,
                    ),
                )
        except Exception:
            # Persistence failure must not replace the original provider,
            # validation, or retrieval error.
            return

    @staticmethod
    def _retrieval_text(request: RecommendationRequest) -> str:
        parts = [
            f"Query type: {request.query_type.value}",
            f"Creative brief: {request.brief}",
        ]
        if request.constraints:
            parts.append("Constraints: " + "; ".join(request.constraints))
        if request.target_platform is not None:
            parts.append(f"Target platform: {request.target_platform}")
        if request.generation_method is not None:
            parts.append(f"Generation method: {request.generation_method}")
        return "\n".join(parts)

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(0, round((perf_counter() - started) * 1_000))

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if isinstance(exc, RecommendationError):
            return exc.error_code
        if isinstance(exc, AlbaError):
            return exc.detail.error_code
        return "RECOMMENDATION_FAILED"


def finalize_recommendation(
    draft: RecommendationDraft,
    context: RecommendationContext,
    *,
    provider_name: str,
    model_name: str,
    repair_attempts_used: int = 0,
) -> PromptRecommendation:
    """Validate grounding and apply deterministic operational-confidence policy."""
    if repair_attempts_used not in {0, 1}:
        raise ValueError("A recommendation may use at most one repair attempt.")

    validate_draft_grounding(draft, context)
    allowed_constraints = {item.constraint_id: item for item in context.constraints}
    unmet = set(draft.unmet_constraint_ids)

    needs_human_review = draft.needs_human_review
    assumptions = list(draft.assumptions)
    rationale = list(draft.rationale)
    if unmet:
        needs_human_review = True
        for constraint_id in draft.unmet_constraint_ids:
            constraint = allowed_constraints[constraint_id]
            _append_unique(
                assumptions,
                f"Constraint {constraint_id} was not covered: {constraint.text}",
                limit=10,
            )

    if context.positive_evidence and not draft.used_positive_evidence_ids:
        needs_human_review = True
        _append_unique(
            assumptions,
            (
                "Approved evidence was retrieved but the provider cited none; "
                "the recommendation is treated as ungrounded."
            ),
            limit=10,
        )

    if context.failure_evidence and not draft.failure_warnings:
        needs_human_review = True
        _append_unique(
            assumptions,
            (
                "Rejected evidence was retrieved but the provider supplied no "
                "grounded failure warnings."
            ),
            limit=10,
        )

    if not context.positive_evidence:
        needs_human_review = True
        _append_unique(
            assumptions,
            "No sufficiently similar approved evidence was retrieved.",
            limit=10,
        )
    if not context.positive_evidence and not context.failure_evidence:
        _append_unique(
            assumptions,
            "No project evidence met the retrieval threshold.",
            limit=10,
        )
        rationale = [
            (
                "This is a general recommendation based only on the supplied "
                "brief and constraints because no project evidence met the "
                "retrieval threshold."
            )
        ]

    confidence = calculate_operational_confidence(
        draft,
        context,
        repair_attempts_used=repair_attempts_used,
    )

    return PromptRecommendation(
        recommended_prompt=draft.recommended_prompt,
        rationale=rationale,
        used_positive_evidence_ids=draft.used_positive_evidence_ids,
        failure_warnings=draft.failure_warnings,
        covered_constraint_ids=draft.covered_constraint_ids,
        unmet_constraint_ids=draft.unmet_constraint_ids,
        assumptions=assumptions,
        provider_confidence=draft.provider_confidence,
        confidence=confidence,
        needs_human_review=needs_human_review,
        platform_notes=draft.platform_notes,
        suggested_parameters=draft.suggested_parameters,
        negative_prompt=draft.negative_prompt,
        constraints=context.constraints,
        repair_attempts_used=repair_attempts_used,
        provider=provider_name,
        model=model_name,
    )


def validate_draft_grounding(
    draft: RecommendationDraft,
    context: RecommendationContext,
    *,
    require_positive_citation: bool = False,
) -> None:
    """Validate evidence roles and complete constraint accounting."""
    allowed_positive = {item.example_id: item for item in context.positive_evidence}
    allowed_failure = {item.example_id: item for item in context.failure_evidence}
    all_evidence_ids = set(allowed_positive).union(allowed_failure)
    used_positive = set(draft.used_positive_evidence_ids)
    warning_ids = {item.evidence_id for item in draft.failure_warnings}
    unknown = used_positive.union(warning_ids).difference(all_evidence_ids)
    if unknown:
        raise FabricatedEvidenceReferenceError(unknown)
    if used_positive.intersection(allowed_failure) or warning_ids.intersection(allowed_positive):
        raise EvidenceStatusMismatchError(
            "Recommendation crossed approved and rejected evidence roles."
        )
    allowed_constraints = {item.constraint_id: item for item in context.constraints}
    covered = set(draft.covered_constraint_ids)
    unmet = set(draft.unmet_constraint_ids)
    unknown_constraints = covered.union(unmet).difference(allowed_constraints)
    if unknown_constraints:
        raise FabricatedConstraintReferenceError(unknown_constraints)
    if covered.intersection(unmet):
        overlap = ", ".join(sorted(covered.intersection(unmet)))
        raise ConstraintAccountingError(
            f"Constraint IDs cannot be both covered and unmet: {overlap}."
        )
    missing_constraints = set(allowed_constraints).difference(covered.union(unmet))
    if missing_constraints:
        missing = ", ".join(sorted(missing_constraints))
        raise ConstraintAccountingError(
            f"Constraint IDs must be accounted for as covered or unmet: {missing}."
        )
    if require_positive_citation and allowed_positive and not used_positive:
        raise MissingPositiveEvidenceCitationError(
            "Approved evidence was retrieved but the provider cited none."
        )


def calculate_operational_confidence(
    draft: RecommendationDraft,
    context: RecommendationContext,
    *,
    repair_attempts_used: int,
) -> float:
    """Calculate an MVP operational heuristic, not a statistical probability."""
    constraints_total = len(context.constraints)
    coverage = len(draft.covered_constraint_ids) / constraints_total if constraints_total else 1.0
    positive_by_id = {item.example_id: item for item in context.positive_evidence}
    cited = [
        positive_by_id[identifier]
        for identifier in draft.used_positive_evidence_ids
        if identifier in positive_by_id
    ]

    if not context.positive_evidence and not context.failure_evidence:
        heuristic = NO_EVIDENCE_CONFIDENCE_MAX
    elif not cited:
        heuristic = UNGROUNDED_POSITIVE_CONFIDENCE_MAX
    else:
        highest_similarity = max(
            0.0,
            min(1.0, max(item.similarity for item in cited)),
        )
        citation_quantity = min(len(cited), 3) / 3
        heuristic = 0.15 + 0.55 * highest_similarity + 0.15 * citation_quantity + 0.15 * coverage

    if draft.unmet_constraint_ids:
        heuristic = min(heuristic, UNMET_CONSTRAINT_CONFIDENCE_MAX)
    if context.positive_evidence and not cited:
        heuristic = min(heuristic, UNGROUNDED_POSITIVE_CONFIDENCE_MAX)
    if context.failure_evidence and not draft.failure_warnings:
        heuristic = min(heuristic, MISSING_FAILURE_WARNING_CONFIDENCE_MAX)
    heuristic -= STRUCTURED_REPAIR_PENALTY * repair_attempts_used
    return round(max(0.0, min(1.0, draft.provider_confidence, heuristic)), 4)


def _append_unique(values: list[str], value: str, *, limit: int) -> None:
    if len(values) >= limit:
        return
    normalized = value.casefold()
    if all(item.casefold() != normalized for item in values):
        values.append(value)
