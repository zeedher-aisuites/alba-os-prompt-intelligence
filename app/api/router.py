"""Top-level API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.web.routes.api import router as web_api_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(web_api_router)
