"""Unit tests for environment-backed configuration."""

from __future__ import annotations

import pytest
from app.core.config import Settings
from pydantic import ValidationError


def test_settings_read_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALBA_APP_NAME", "Configured Alba")
    monkeypatch.setenv("ALBA_ENVIRONMENT", "test")
    monkeypatch.setenv("ALBA_DEBUG", "true")
    monkeypatch.setenv(
        "ALBA_TEST_DATABASE_URL",
        "postgresql+asyncpg://test:test@127.0.0.1:5432/alba_os_test",
    )
    monkeypatch.setenv("ALBA_EMBEDDING_BATCH_SIZE", "32")
    monkeypatch.setenv("ALBA_RETRIEVAL_MAX_LIMIT", "12")
    monkeypatch.setenv("ALBA_RECOMMENDATION_CONTEXT_MAX_CHARACTERS", "20000")
    monkeypatch.setenv("ALBA_RECOMMENDATION_MAX_REPAIR_ATTEMPTS", "0")

    settings = Settings()

    assert settings.app_name == "Configured Alba"
    assert settings.environment == "test"
    assert settings.debug is True
    assert settings.test_database_url.get_secret_value().path == "/alba_os_test"
    assert settings.embedding_batch_size == 32
    assert settings.retrieval_max_limit == 12
    assert settings.recommendation_context_max_characters == 20_000
    assert settings.recommendation_max_repair_attempts == 0


def test_settings_reject_unknown_environment() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="staging")  # pyright: ignore[reportArgumentType]


def test_database_url_repr_masks_placeholder_password() -> None:
    settings = Settings()

    assert settings.embedding_model == "embeddinggemma:300m"
    assert settings.recommendation_model == "qwen2.5:3b"
    assert "alba_dev" not in repr(settings)
    assert "alba_dev" not in repr(settings.database_url)
    assert "alba_dev" not in repr(settings.test_database_url)
