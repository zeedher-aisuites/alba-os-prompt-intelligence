"""Typed application configuration."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, PostgresDsn, Secret
from pydantic_settings import BaseSettings, SettingsConfigDict

EnvironmentName = Literal["development", "test", "production"]
DEFAULT_DATABASE_URL = "postgresql+asyncpg://alba:alba_dev@127.0.0.1:5432/alba_os"
DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://alba:alba_dev@127.0.0.1:5432/alba_os_test"


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
    database_url: Secret[PostgresDsn] = Secret(PostgresDsn(DEFAULT_DATABASE_URL))
    test_database_url: Secret[PostgresDsn] = Secret(PostgresDsn(DEFAULT_TEST_DATABASE_URL))
    database_echo: bool = False
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_pool_timeout: float = Field(default=30.0, gt=0, le=300)
    database_pool_recycle: int = Field(default=1800, ge=1)
    ollama_base_url: HttpUrl = HttpUrl("http://127.0.0.1:11434")
    embedding_model: str = Field(default="embeddinggemma:300m", min_length=1, max_length=100)
    embedding_timeout: float = Field(default=30.0, gt=0, le=300)
    embedding_batch_size: int = Field(default=16, ge=1, le=256)
    retrieval_max_limit: int = Field(default=20, ge=1, le=100)
    recommendation_model: str = Field(default="qwen2.5:3b", min_length=1, max_length=100)
    recommendation_timeout: float = Field(default=60.0, gt=0, le=600)
    recommendation_context_max_characters: int = Field(default=18_000, ge=4_000, le=100_000)
    recommendation_evidence_field_max_characters: int = Field(default=1_200, ge=200, le=8_000)
    recommendation_max_output_tokens: int = Field(default=1_200, ge=200, le=8_000)
    recommendation_max_repair_attempts: int = Field(default=1, ge=0, le=1)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide immutable settings snapshot."""
    return Settings()
