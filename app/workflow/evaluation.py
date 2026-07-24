"""Deterministic workflow scenarios and objective metric aggregation."""

from __future__ import annotations

from collections.abc import Iterable
from statistics import median

from app.workflow.schemas import (
    HumanDecision,
    WorkflowEvaluationCase,
    WorkflowEvaluationObservation,
    WorkflowEvaluationReport,
)

WORKFLOW_EVALUATION_CASES = (
    WorkflowEvaluationCase(case_id="direct-approve", expected_decision=HumanDecision.APPROVE),
    WorkflowEvaluationCase(case_id="direct-reject", expected_decision=HumanDecision.REJECT),
    WorkflowEvaluationCase(
        case_id="revise-with-feedback",
        expected_decision=HumanDecision.APPROVE,
        expects_revision=True,
    ),
    WorkflowEvaluationCase(
        case_id="insufficient-evidence",
        expected_decision=HumanDecision.APPROVE,
    ),
    WorkflowEvaluationCase(
        case_id="prompt-injection-as-data",
        expected_decision=HumanDecision.REJECT,
    ),
    WorkflowEvaluationCase(
        case_id="video-continuity",
        expected_decision=HumanDecision.APPROVE,
    ),
    WorkflowEvaluationCase(
        case_id="branding-constraints",
        expected_decision=HumanDecision.APPROVE,
    ),
    WorkflowEvaluationCase(
        case_id="restart-new-runtime",
        expected_decision=HumanDecision.APPROVE,
    ),
    WorkflowEvaluationCase(
        case_id="provider-failure",
        expected_decision=None,
        expects_failure=True,
    ),
)


def build_evaluation_report(
    observations: list[WorkflowEvaluationObservation],
    *,
    label: str,
) -> WorkflowEvaluationReport:
    """Aggregate only deterministic runtime and persistence measurements."""
    count = len(observations)
    if count == 0:
        return WorkflowEvaluationReport(
            label=label,
            case_count=0,
            checkpoint_persistence_rate=0,
            successful_resume_rate=0,
            valid_transition_rate=0,
            duplicate_terminal_decision_rate=0,
            human_feedback_incorporation_rate=0,
            failed_run_persistence_rate=0,
            latency_to_interrupt_p50_ms=0,
            latency_after_resume_p50_ms=0,
        )

    resume_cases = [item for item in observations if item.resume_expected]
    feedback_cases = [item for item in observations if item.feedback_expected]
    failure_cases = [item for item in observations if item.failure_expected]
    return WorkflowEvaluationReport(
        label=label,
        case_count=count,
        checkpoint_persistence_rate=_rate(item.checkpoint_persisted for item in observations),
        successful_resume_rate=_rate(item.resume_succeeded for item in resume_cases),
        valid_transition_rate=_rate(item.transition_valid for item in observations),
        duplicate_terminal_decision_rate=_rate(
            item.duplicate_terminal_decision for item in observations
        ),
        human_feedback_incorporation_rate=_rate(
            item.feedback_incorporated for item in feedback_cases
        ),
        failed_run_persistence_rate=_rate(item.failed_run_persisted for item in failure_cases),
        latency_to_interrupt_p50_ms=median(item.latency_to_interrupt_ms for item in resume_cases),
        latency_after_resume_p50_ms=median(
            item.latency_after_resume_ms for item in observations if item.resume_expected
        ),
    )


def _rate(values: Iterable[bool]) -> float:
    materialized = list(values)
    if not materialized:
        return 1.0
    return sum(bool(item) for item in materialized) / len(materialized)
