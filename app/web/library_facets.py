"""Canonical values and display labels for the read-only experience library."""

from __future__ import annotations

import re

# These are presentation overrides only. They never decide which platforms are
# selectable: every option still comes from the PostgreSQL corpus query.
_PLATFORM_DISPLAY_OVERRIDES = {
    "openai": "OpenAI",
    "pixverse": "PixVerse",
}


def normalize_platform(value: str) -> str:
    """Collapse insignificant whitespace and compare platform values case-insensitively."""
    return _normalize_spaces(value)


def normalize_generation_method(value: str) -> str:
    """Treat separators in a generation-method identifier consistently."""
    return re.sub(r"[\s_-]+", "-", value.strip().casefold())


def normalize_tag(value: str) -> str:
    """Return an exact canonical tag value without changing persisted spelling."""
    return re.sub(r"[\s_-]+", "-", value.strip().casefold())


def platform_label(value: str) -> str:
    """Create a legible platform label without maintaining a selectable-brand catalog."""
    return _PLATFORM_DISPLAY_OVERRIDES.get(value, _title_words(value))


def generation_method_label(value: str) -> str:
    """Render a canonical method identifier as a short human label."""
    words = value.replace("-", " ").split()
    return " ".join(word.capitalize() if index == 0 else word for index, word in enumerate(words))


def enum_label(value: str) -> str:
    """Render an enum value as a short human label."""
    return _title_words(value.replace("_", " "))


def _normalize_spaces(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def _title_words(value: str) -> str:
    return " ".join(word.capitalize() for word in value.split())
