"""FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api.errors import register_exception_handlers
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.db.session import Database
from app.main_metadata import APP_VERSION
from app.web.readiness import ReadinessCache
from app.web.routes.pages import router as pages_router
from app.web.routes.workflows import router as workflows_router


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
) -> FastAPI:
    """Create and configure an Alba OS FastAPI application."""
    resolved_settings = settings or get_settings()
    resolved_database = database or Database(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        yield
        await resolved_database.dispose()

    application = FastAPI(
        title=resolved_settings.app_name,
        version=APP_VERSION,
        debug=resolved_settings.debug,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.state.database = resolved_database
    application.state.readiness_cache = ReadinessCache()
    application.dependency_overrides[get_settings] = lambda: resolved_settings
    register_exception_handlers(application)
    application.mount("/static", StaticFiles(directory="app/web/static"), name="static")
    application.include_router(pages_router)
    application.include_router(workflows_router)
    application.include_router(api_router)

    @application.middleware("http")
    async def local_security_headers(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Apply baseline browser protections compatible with local static assets."""
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; connect-src 'self'; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'none'",
        )
        return response

    return application


app = create_app()
