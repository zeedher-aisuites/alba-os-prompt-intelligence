"""HTTP representation of expected application errors."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import AlbaError
from app.domain.exceptions import (
    ConstraintViolationError,
    DatabaseUnavailableError,
    DuplicateSlugError,
    EntityNotFoundError,
    ResourceInUseError,
)


def _status_code(error: AlbaError) -> int:
    if isinstance(error, EntityNotFoundError):
        return 404
    if isinstance(error, DatabaseUnavailableError):
        return 503
    if isinstance(
        error,
        (ConstraintViolationError, DuplicateSlugError, ResourceInUseError),
    ):
        return 409
    return 400


async def handle_alba_error(_: Request, error: Exception) -> JSONResponse:
    """Render a known Alba error without exposing infrastructure details."""
    if not isinstance(error, AlbaError):
        raise error
    return JSONResponse(
        status_code=_status_code(error),
        content=asdict(error.detail),
    )


def register_exception_handlers(application: FastAPI) -> None:
    """Register stable JSON responses for known Alba errors."""
    application.add_exception_handler(AlbaError, handle_alba_error)
