"""Typed retrieval evaluation results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvaluationMetrics(BaseModel):
    """Aggregate information-retrieval and latency metrics."""

    model_config = ConfigDict(frozen=True)

    cases: int = Field(ge=0)
    recall_at_3: float = Field(ge=0, le=1)
    recall_at_5: float = Field(ge=0, le=1)
    mean_reciprocal_rank: float = Field(ge=0, le=1)
    precision_at_5: float = Field(ge=0, le=1)
    zero_result_rate: float = Field(ge=0, le=1)
    latency_p50_ms: float = Field(ge=0)
    latency_p95_ms: float = Field(ge=0)


class EvaluationCaseResult(BaseModel):
    """One measured query and its ranked relevance outcome."""

    model_config = ConfigDict(frozen=True)

    key: str
    retrieval_kind: Literal["approved", "failure"]
    relevant_ids: list[str]
    retrieved_ids: list[str]
    latency_ms: float = Field(ge=0)


class RetrievalEvaluationReport(BaseModel):
    """Evaluation metrics separated by positive and failure retrieval."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    positive: EvaluationMetrics
    failure: EvaluationMetrics
    overall: EvaluationMetrics
    cases: list[EvaluationCaseResult]
