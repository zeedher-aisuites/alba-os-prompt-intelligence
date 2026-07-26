"""Deterministic metric tests for the Stage 4 workflow evaluation."""

from __future__ import annotations

from app.workflow.evaluation import (
    WORKFLOW_EVALUATION_CASES,
    build_evaluation_report,
)
from app.workflow.schemas import WorkflowEvaluationObservation
from scripts.evaluate_workflows import expected_terminal_phase


def observation(
    case_id: str,
    *,
    success: bool = True,
    feedback_expected: bool = False,
    failure_expected: bool = False,
) -> WorkflowEvaluationObservation:
    return WorkflowEvaluationObservation(
        case_id=case_id,
        checkpoint_persisted=success,
        resume_expected=not failure_expected,
        resume_succeeded=success and not failure_expected,
        transition_valid=success,
        duplicate_terminal_decision=False,
        feedback_expected=feedback_expected,
        feedback_incorporated=success and feedback_expected,
        failure_expected=failure_expected,
        failed_run_persisted=success and failure_expected,
        latency_to_interrupt_ms=100,
        latency_after_resume_ms=50,
    )


def test_dataset_covers_required_workflow_scenarios() -> None:
    case_ids = {item.case_id for item in WORKFLOW_EVALUATION_CASES}

    assert 8 <= len(WORKFLOW_EVALUATION_CASES) <= 12
    assert "direct-approve" in case_ids
    assert "direct-reject" in case_ids
    assert "revise-with-feedback" in case_ids
    assert "insufficient-evidence" in case_ids
    assert "prompt-injection-as-data" in case_ids
    assert "restart-new-runtime" in case_ids
    assert "provider-failure" in case_ids


def test_human_reject_is_a_completed_workflow_with_a_separate_outcome() -> None:
    rejected = next(item for item in WORKFLOW_EVALUATION_CASES if item.case_id == "direct-reject")

    assert expected_terminal_phase(rejected).value == "completed"


def test_report_uses_objective_rates_and_medians() -> None:
    observations = [
        observation("approve"),
        observation("revision", feedback_expected=True),
        observation("failure", failure_expected=True),
    ]

    report = build_evaluation_report(observations, label="deterministic fake")

    assert report.case_count == 3
    assert report.checkpoint_persistence_rate == 1
    assert report.successful_resume_rate == 1
    assert report.valid_transition_rate == 1
    assert report.duplicate_terminal_decision_rate == 0
    assert report.human_feedback_incorporation_rate == 1
    assert report.failed_run_persistence_rate == 1
    assert report.latency_to_interrupt_p50_ms == 100
    assert report.latency_after_resume_p50_ms == 50


def test_report_excludes_safe_pre_interrupt_failure_from_resume_metrics() -> None:
    reached_interrupt = observation("reached-interrupt")
    safe_pre_interrupt_failure = observation("safe-pre-interrupt").model_copy(
        update={
            "resume_expected": False,
            "resume_succeeded": False,
            "transition_valid": False,
            "latency_to_interrupt_ms": 9_999,
            "latency_after_resume_ms": 0,
        }
    )

    report = build_evaluation_report(
        [reached_interrupt, safe_pre_interrupt_failure],
        label="separate denominators",
    )

    assert report.case_count == 2
    assert report.successful_resume_rate == 1
    assert report.valid_transition_rate == 0.5
    assert report.latency_to_interrupt_p50_ms == 100
