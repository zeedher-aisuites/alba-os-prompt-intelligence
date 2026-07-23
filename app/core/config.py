"""Typed application configuration."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

EnvironmentName = Literal["development", "test", "production"]


class Settings(BaseSettings):
    """Environment-backed application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ALBA_",
        extra="ignore",
        frozen=True,
    )

    app_name: str = Field(
        default="Alba OS Prompt Intelligence MVP",
        min_length=1,
    )
    environment: EnvironmentName = "development"
    debug: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide immutable settings snapshot."""
    return Settings()
