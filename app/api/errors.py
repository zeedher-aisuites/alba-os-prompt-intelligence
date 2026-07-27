"""HTTP representation of expected application errors."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Literal, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.types import ExceptionHandler

from app.core.exceptions import AlbaError
from app.domain.exceptions import (
    ConstraintViolationError,
    DatabaseUnavailableError,
    DuplicateSlugError,
    EntityNotFoundError,
    ResourceInUseError,
)
from app.recommendation.exceptions import (
    RecommendationError,
    RecommendationProviderUnavailableError,
)
from app.web.errors import WebDependencyUnavailableError, html_error_response, wants_html
from app.web.schemas import ApiErrorEnvelope, ApiErrorView
from app.workflow.exceptions import (
    WorkflowAlreadyExistsError,
    WorkflowCheckpointSchemaMissingError,
    WorkflowCheckpointUnavailableError,
    WorkflowNotFoundError,
    WorkflowNotWaitingError,
    WorkflowResumeReconciliationRejectedError,
    WorkflowResumeReconciliationRequiredError,
    WorkflowRevisionLimitError,
)

logger = logging.getLogger(__name__)


def _status_code(error: AlbaError) -> int:
    if isinstance(error, EntityNotFoundError):
        return 404
    if isinstance(error, (DatabaseUnavailableError, WorkflowCheckpointUnavailableError)):
        return 503
    if isinstance(
        error,
        (
            ConstraintViolationError,
            DuplicateSlugError,
            ResourceInUseError,
            WorkflowAlreadyExistsError,
            WorkflowNotWaitingError,
            WorkflowRevisionLimitError,
            WorkflowResumeReconciliationRequiredError,
            WorkflowResumeReconciliationRejectedError,
        ),
    ):
        return 409
    if isinstance(error, (WorkflowCheckpointSchemaMissingError, WebDependencyUnavailableError)):
        return 503
    if isinstance(error, WorkflowNotFoundError):
        return 404
    return 400


async def handle_alba_error(request: Request, error: Exception) -> Response:
    """Render a known Alba error without exposing infrastructure details."""
    if not isinstance(error, AlbaError):
        raise error
    status_code = _status_code(error)
    if wants_html(request):
        template_status = cast(
            Literal[404, 409, 422, 503],
            status_code if status_code in {404, 409, 422, 503} else 422,
        )
        return html_error_response(
            request,
            status_code=template_status,
            code=error.detail.error_code,
            message=error.detail.message,
        )
    if request.url.path.startswith("/api/v1/"):
        return JSONResponse(
            status_code=status_code,
            content=ApiErrorEnvelope(
                error=ApiErrorView(
                    code=error.detail.error_code,
                    message=error.detail.message,
                    trace_id=error.detail.trace_id,
                )
            ).model_dump(mode="json"),
        )
    return JSONResponse(
        status_code=status_code,
        content=asdict(error.detail),
    )


async def handle_request_validation_error(
    request: Request,
    _: RequestValidationError,
) -> Response:
    """Keep versioned API validation errors structured and internal-detail free."""
    message = "The request did not satisfy the expected input contract."
    if wants_html(request):
        return html_error_response(
            request,
            status_code=422,
            code="INPUT_VALIDATION_ERROR",
            message=message,
        )
    if request.url.path.startswith("/api/v1/"):
        return JSONResponse(
            status_code=422,
            content=ApiErrorEnvelope(
                error=ApiErrorView(code="INPUT_VALIDATION_ERROR", message=message)
            ).model_dump(mode="json"),
        )
    return JSONResponse(
        status_code=422,
        content={"error_code": "INPUT_VALIDATION_ERROR", "message": message},
    )


async def handle_recommendation_error(request: Request, error: Exception) -> Response:
    """Map provider failures to safe availability responses across delivery surfaces."""
    if not isinstance(error, RecommendationError):
        raise error
    status_code = 503 if isinstance(error, RecommendationProviderUnavailableError) else 422
    code = error.error_code
    message = (
        "The local recommendation provider is unavailable."
        if status_code == 503
        else "The recommendation request could not be completed safely."
    )
    if wants_html(request):
        return html_error_response(request, status_code=status_code, code=code, message=message)
    if request.url.path.startswith("/api/v1/"):
        return JSONResponse(
            status_code=status_code,
            content=ApiErrorEnvelope(error=ApiErrorView(code=code, message=message)).model_dump(
                mode="json"
            ),
        )
    return JSONResponse(
        status_code=status_code,
        content={"error_code": code, "message": message},
    )


async def handle_unexpected_error(request: Request, _: Exception) -> Response:
    """Log a local diagnostic while keeping every public 500 response opaque."""
    logger.exception("Unexpected local application error for %s", request.url.path)
    code = "INTERNAL_SERVER_ERROR"
    message = "The request could not be completed safely."
    if wants_html(request):
        return html_error_response(request, status_code=500, code=code, message=message)
    if request.url.path.startswith("/api/v1/"):
        return JSONResponse(
            status_code=500,
            content=ApiErrorEnvelope(error=ApiErrorView(code=code, message=message)).model_dump(
                mode="json"
            ),
        )
    return JSONResponse(status_code=500, content={"error_code": code, "message": message})


def register_exception_handlers(application: FastAPI) -> None:
    """Register stable JSON responses for known Alba errors."""
    application.add_exception_handler(AlbaError, handle_alba_error)
    application.add_exception_handler(
        RequestValidationError,
        cast(ExceptionHandler, handle_request_validation_error),
    )
    application.add_exception_handler(RecommendationError, handle_recommendation_error)
    application.add_exception_handler(Exception, handle_unexpected_error)
