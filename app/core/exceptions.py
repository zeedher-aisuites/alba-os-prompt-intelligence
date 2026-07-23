"""Typed application errors shared across delivery mechanisms."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    """Stable, serializable error information."""

    error_code: str
    message: str
    retryable: bool = False
    trace_id: str | None = None


class AlbaError(Exception):
    """Base exception for expected Alba OS failures."""

    def __init__(self, detail: ErrorDetail) -> None:
        super().__init__(detail.message)
        self.detail = detail
