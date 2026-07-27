"""Contracts and launcher behavior for the local Stage 5 delivery surface."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.domain.enums import GenerationStatus, QueryType
from app.domain.schemas import PromptExampleRead
from app.web.presenters import embedding_state, format_utc, short_identifier
from app.web.schemas import WorkflowResumeInput, WorkflowStartInput
from app.workflow.schemas import HumanDecision
from pydantic import ValidationError
from scripts import run_web


def test_web_start_schema_normalizes_thread_id_and_rejects_unknown_provider() -> None:
    payload = WorkflowStartInput(
        project_id=uuid4(),
        query_type=QueryType.ART,
        brief="Create a clear editorial image.",
        constraints=["Keep the composition"],
        provider="fake",
        thread_id="  local-thread-1  ",
    )

    assert payload.thread_id == "local-thread-1"
    with pytest.raises(ValidationError):
        WorkflowStartInput(
            project_id=uuid4(),
            query_type=QueryType.ART,
            brief="Create a clear editorial image.",
            provider="untrusted",  # type: ignore[arg-type]
        )


def test_web_resume_schema_requires_feedback_for_revision() -> None:
    with pytest.raises(ValidationError):
        WorkflowResumeInput(decision=HumanDecision.REVISE)

    approved = WorkflowResumeInput(decision=HumanDecision.APPROVE)
    revised = WorkflowResumeInput(
        decision=HumanDecision.REVISE,
        feedback="Retain the editorial crop.",
    )

    assert approved.feedback is None
    assert revised.feedback == "Retain the editorial crop."


def test_presenter_uses_utc_and_never_needs_a_vector() -> None:
    timestamp = datetime(2026, 1, 1, 7, 0, tzinfo=UTC)
    example = PromptExampleRead(
        id=uuid4(),
        project_id=uuid4(),
        base_prompt="Safe prompt",
        expected_result="Safe result",
        generated_image_description=None,
        generation_method="image",
        target_platform="web",
        query_type=QueryType.ART,
        status=GenerationStatus.APPROVED,
        review_notes=None,
        rejection_reason=None,
        quality_score=None,
        image_path=None,
        image_sha256=None,
        tags=[],
        embedding_text="Safe prompt",
        embedding_provider=None,
        embedding_model=None,
        embedding_source_hash=None,
        embedded_at=None,
        created_at=timestamp,
        updated_at=timestamp,
    )

    assert embedding_state(example) == "missing"
    assert format_utc(timestamp + timedelta(hours=1)) == "2026-01-01 08:00:00 UTC"
    assert short_identifier("1234567890abcdef") == "12345678…cdef"


def test_local_launcher_parses_loopback_options_and_disables_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_uvicorn_run(*_: object, **kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(run_web, "configure_event_loop_policy", lambda: False)
    monkeypatch.setattr(run_web.uvicorn, "run", fake_uvicorn_run)
    run_web.run_server(["--host", "::1", "--port", "8123"])

    assert captured == {
        "host": "::1",
        "port": 8123,
        "loop": run_web.SELECTOR_LOOP_FACTORY,
        "reload": False,
    }
    with pytest.raises(SystemExit):
        run_web.parse_args(["--host", "0.0.0.0"])


def test_local_launcher_forces_a_selector_loop_for_psycopg() -> None:
    loop = run_web.selector_loop_factory()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()
