"""Unit tests for environment-backed configuration."""

from __future__ import annotations

import pytest
from app.core.config import Settings
from pydantic import ValidationError


def test_settings_read_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALBA_APP_NAME", "Configured Alba")
    monkeypatch.setenv("ALBA_ENVIRONMENT", "test")
    monkeypatch.setenv("ALBA_DEBUG", "true")

    settings = Settings()

    assert settings.app_name == "Configured Alba"
    assert settings.environment == "test"
    assert settings.debug is True


def test_settings_reject_unknown_environment() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="staging")  # pyright: ignore[reportArgumentType]
