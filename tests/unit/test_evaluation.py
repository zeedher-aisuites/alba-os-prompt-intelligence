"""Synthetic dataset and retrieval metric tests."""

from __future__ import annotations

from app.domain.enums import GenerationStatus, QueryType
from app.evaluation.cases import EVALUATION_CASES
from app.evaluation.demo_data import demo_example_specs
from app.evaluation.metrics import calculate_metrics
from app.evaluation.schemas import EvaluationCaseResult


def test_demo_dataset_has_expected_size_distribution_and_failures() -> None:
    examples = demo_example_specs()

    assert len(examples) == 64
    assert {example.query_type for example in examples} == set(QueryType)
    assert sum(example.status == GenerationStatus.APPROVED for example in examples) == 24
    assert sum(example.status == GenerationStatus.IN_REVIEW for example in examples) == 16
    assert sum(example.status == GenerationStatus.REJECTED for example in examples) == 24
    failure_tags = {
        tag for example in examples for tag in example.tags if tag.startswith("failure:")
    }
    assert {
        "failure:outfit-changed",
        "failure:identity-inconsistent",
        "failure:direction-inverted",
        "failure:hairstyle-altered",
        "failure:hands-defective",
        "failure:logo-deformed",
        "failure:continuity-broken",
    }.issubset(failure_tags)
    assert len({example.key for example in examples}) == 64


def test_evaluation_has_ten_positive_and_ten_failure_cases() -> None:
    assert len(EVALUATION_CASES) == 20
    assert sum(case.retrieval_kind == "approved" for case in EVALUATION_CASES) == 10
    assert sum(case.retrieval_kind == "failure" for case in EVALUATION_CASES) == 10
    assert len({case.key for case in EVALUATION_CASES}) == 20


def test_metric_calculation_uses_actual_ranked_ids() -> None:
    metrics = calculate_metrics(
        [
            EvaluationCaseResult(
                key="hit",
                retrieval_kind="approved",
                relevant_ids=["a"],
                retrieved_ids=["b", "a"],
                latency_ms=10,
            ),
            EvaluationCaseResult(
                key="miss",
                retrieval_kind="approved",
                relevant_ids=["c"],
                retrieved_ids=[],
                latency_ms=30,
            ),
        ]
    )

    assert metrics.recall_at_3 == 0.5
    assert metrics.recall_at_5 == 0.5
    assert metrics.mean_reciprocal_rank == 0.25
    assert metrics.precision_at_5 == 0.1
    assert metrics.zero_result_rate == 0.5
    assert metrics.latency_p50_ms == 20
    assert metrics.latency_p95_ms == 29
