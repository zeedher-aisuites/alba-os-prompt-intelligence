"""Read-only validation tests for the user-owned prompt corpus contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from pytest import CaptureFixture
from scripts.validate_prompt_corpus import main, validate_corpus

FIXTURES = Path("tests/fixtures/corpus")


def test_template_is_strictly_valid() -> None:
    report = cast(dict[str, Any], validate_corpus(Path("data/templates/prompt-corpus-v1.csv")))

    assert report["schema"] == "prompt-corpus-v1"
    assert report["rows_read"] == 2
    assert report["error_count"] == 0
    assert report["warning_count"] == 0
    assert report["database_written"] is False
    assert report["embeddings_generated"] is False


def test_validator_reports_duplicate_external_id_and_normalizes_tags(
    capsys: CaptureFixture[str],
) -> None:
    corpus = FIXTURES / "duplicates.csv"

    exit_code = main([str(corpus), "--strict"])
    report = cast(dict[str, Any], json.loads(capsys.readouterr().out))
    errors = cast(list[dict[str, object]], report["errors"])
    normalized_tags = cast(dict[str, list[str]], report["normalized_tags"])

    assert exit_code == 1
    assert any(issue["code"] == "DUPLICATE_EXTERNAL_ID" for issue in errors)
    assert normalized_tags["2"] == ["Art"]
    assert report["database_written"] is False


def test_validator_rejects_missing_columns_without_rewriting_input() -> None:
    corpus = FIXTURES / "missing-columns.csv"
    original = corpus.read_text(encoding="utf-8")

    report = cast(dict[str, Any], validate_corpus(corpus))
    errors = cast(list[dict[str, object]], report["errors"])

    assert cast(int, report["error_count"]) > 0
    assert any(issue["code"] == "MISSING_COLUMN" for issue in errors)
    assert corpus.read_text(encoding="utf-8") == original
