"""Run measured retrieval evaluation against a seeded PostgreSQL dataset."""

from __future__ import annotations

from collections import defaultdict
from time import perf_counter
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.prompt_example import PromptExample
from app.db.repositories.project import ProjectRepository
from app.domain.schemas import RetrievalQuery
from app.embeddings.protocol import EmbeddingProvider
from app.evaluation.cases import EVALUATION_CASES, EvaluationCase
from app.evaluation.demo_data import DEMO_PROJECT_SLUG
from app.evaluation.metrics import calculate_metrics
from app.evaluation.schemas import EvaluationCaseResult, RetrievalEvaluationReport
from app.retrieval.service import RetrievalService


class EvaluationDatasetError(RuntimeError):
    """Raised when the deterministic evaluation evidence is incomplete."""


class RetrievalEvaluationRunner:
    """Measure twenty fixed queries without inventing relevance labels."""

    def __init__(
        self,
        session: AsyncSession,
        provider: EmbeddingProvider,
        *,
        maximum_limit: int = 20,
    ) -> None:
        self._session = session
        self._provider = provider
        self._retrieval = RetrievalService(
            session,
            provider,
            maximum_limit=maximum_limit,
        )

    async def run(
        self,
        cases: tuple[EvaluationCase, ...] = EVALUATION_CASES,
    ) -> RetrievalEvaluationReport:
        """Run each case and return actually measured metrics."""
        project = await ProjectRepository(self._session).get_by_slug(DEMO_PROJECT_SLUG)
        if project is None:
            raise EvaluationDatasetError("The retrieval demonstration dataset has not been seeded.")
        relevant_ids = await self._relevant_ids(project.id)
        case_results: list[EvaluationCaseResult] = []
        for case in cases:
            expected = relevant_ids.get(case.relevant_tag, set())
            if not expected:
                raise EvaluationDatasetError(
                    f"No example has evaluation tag '{case.relevant_tag}'."
                )
            query = RetrievalQuery(
                text=case.query,
                project_id=project.id,
                limit=5,
            )
            started = perf_counter()
            if case.retrieval_kind == "approved":
                result = await self._retrieval.search_approved_examples(query)
            else:
                result = await self._retrieval.search_failure_patterns(query)
            latency_ms = (perf_counter() - started) * 1000
            case_results.append(
                EvaluationCaseResult(
                    key=case.key,
                    retrieval_kind=case.retrieval_kind,
                    relevant_ids=sorted(str(identifier) for identifier in expected),
                    retrieved_ids=[str(item.id) for item in result.items],
                    latency_ms=latency_ms,
                )
            )

        positive = [result for result in case_results if result.retrieval_kind == "approved"]
        failures = [result for result in case_results if result.retrieval_kind == "failure"]
        return RetrievalEvaluationReport(
            provider=self._provider.provider_name,
            model=self._provider.model_name,
            positive=calculate_metrics(positive),
            failure=calculate_metrics(failures),
            overall=calculate_metrics(case_results),
            cases=case_results,
        )

    async def _relevant_ids(self, project_id: UUID) -> dict[str, set[UUID]]:
        statement = select(PromptExample.id, PromptExample.tags).where(
            PromptExample.project_id == project_id
        )
        rows = (await self._session.execute(statement)).all()
        by_tag: dict[str, set[UUID]] = defaultdict(set)
        for identifier, tags in rows:
            for tag in tags:
                if tag.startswith("relevant:"):
                    by_tag[tag].add(identifier)
        return dict(by_tag)
