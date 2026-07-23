"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.main_metadata import APP_VERSION


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure an Alba OS FastAPI application."""
    resolved_settings = settings or get_settings()
    application = FastAPI(
        title=resolved_settings.app_name,
        version=APP_VERSION,
        debug=resolved_settings.debug,
    )
    application.dependency_overrides[get_settings] = lambda: resolved_settings
    application.include_router(api_router)
    return application


app = create_app()
