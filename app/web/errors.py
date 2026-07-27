"""Web-specific safe errors and HTML error rendering helpers."""

from __future__ import annotations

from typing import Literal

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.exceptions import AlbaError, ErrorDetail


class WebDependencyUnavailableError(AlbaError):
    """Raised when a requested local provider is not ready to serve a workflow."""

    def __init__(self, dependency: str) -> None:
        super().__init__(
            ErrorDetail(
                error_code="WEB_DEPENDENCY_UNAVAILABLE",
                message=f"The required local dependency '{dependency}' is unavailable.",
                retryable=True,
            )
        )


def wants_html(request: Request) -> bool:
    """Return whether a browser page, rather than a versioned API, was requested."""
    return not request.url.path.startswith("/api/") and "text/html" in request.headers.get(
        "accept", "text/html"
    )


def html_error_response(
    request: Request,
    *,
    status_code: Literal[404, 409, 422, 500, 503],
    code: str,
    message: str,
) -> HTMLResponse:
    """Render a safe local error page using autoescaped template values."""
    templates = Jinja2Templates(directory="app/web/templates")
    return templates.TemplateResponse(
        request=request,
        name=f"errors/{status_code}.html",
        context={"error_code": code, "error_message": message},
        status_code=status_code,
    )
