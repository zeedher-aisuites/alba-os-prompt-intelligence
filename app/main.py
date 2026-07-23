"""FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.db.session import Database
from app.main_metadata import APP_VERSION


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
        lifespan=lifespan,
    )
    application.state.database = resolved_database
    application.dependency_overrides[get_settings] = lambda: resolved_settings
    register_exception_handlers(application)
    application.include_router(api_router)
    return application


app = create_app()
