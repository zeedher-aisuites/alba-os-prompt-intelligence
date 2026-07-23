"""Pure retrieval metric calculations."""

from __future__ import annotations

from collections.abc import Sequence

from app.evaluation.schemas import EvaluationCaseResult, EvaluationMetrics


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def calculate_metrics(results: Sequence[EvaluationCaseResult]) -> EvaluationMetrics:
    """Calculate macro retrieval metrics from measured ranked results."""
    if not results:
        return EvaluationMetrics(
            cases=0,
            recall_at_3=0,
            recall_at_5=0,
            mean_reciprocal_rank=0,
            precision_at_5=0,
            zero_result_rate=0,
            latency_p50_ms=0,
            latency_p95_ms=0,
        )

    recall_at_3 = 0.0
    recall_at_5 = 0.0
    reciprocal_rank = 0.0
    precision_at_5 = 0.0
    zero_results = 0
    for result in results:
        relevant = set(result.relevant_ids)
        retrieved = result.retrieved_ids
        recall_at_3 += len(relevant.intersection(retrieved[:3])) / len(relevant)
        recall_at_5 += len(relevant.intersection(retrieved[:5])) / len(relevant)
        precision_at_5 += len(relevant.intersection(retrieved[:5])) / 5
        if not retrieved:
            zero_results += 1
        for rank, identifier in enumerate(retrieved, start=1):
            if identifier in relevant:
                reciprocal_rank += 1 / rank
                break

    count = len(results)
    latencies = [result.latency_ms for result in results]
    return EvaluationMetrics(
        cases=count,
        recall_at_3=recall_at_3 / count,
        recall_at_5=recall_at_5 / count,
        mean_reciprocal_rank=reciprocal_rank / count,
        precision_at_5=precision_at_5 / count,
        zero_result_rate=zero_results / count,
        latency_p50_ms=_percentile(latencies, 0.50),
        latency_p95_ms=_percentile(latencies, 0.95),
    )
