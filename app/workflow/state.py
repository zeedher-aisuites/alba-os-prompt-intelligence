"""JSON-serializable LangGraph state definition."""

from __future__ import annotations

from typing import TypedDict

from pydantic import JsonValue


class RecommendationWorkflowState(TypedDict):
    """Durable state; runtime dependencies deliberately live elsewhere."""

    workflow_id: str
    thread_id: str
    run_id: str | None
    project_id: str
    request: dict[str, JsonValue]
    phase: str
    recommendation_context: dict[str, JsonValue] | None
    positive_evidence: list[dict[str, JsonValue]]
    failure_evidence: list[dict[str, JsonValue]]
    recommendation: dict[str, JsonValue] | None
    critique: dict[str, JsonValue] | None
    revision_count: int
    human_decision: str | None
    human_feedback: str | None
    error_code: str | None
    started_at: str
    updated_at: str


class RecommendationWorkflowUpdate(TypedDict, total=False):
    """Explicit partial state update returned by one graph node."""

    run_id: str | None
    phase: str
    recommendation_context: dict[str, JsonValue] | None
    positive_evidence: list[dict[str, JsonValue]]
    failure_evidence: list[dict[str, JsonValue]]
    recommendation: dict[str, JsonValue] | None
    critique: dict[str, JsonValue] | None
    revision_count: int
    human_decision: str | None
    human_feedback: str | None
    error_code: str | None
    updated_at: str
