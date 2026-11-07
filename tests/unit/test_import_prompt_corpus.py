"""Unit tests for the prompt-corpus importer mapping (no database)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.domain.enums import GenerationStatus, QueryType
from scripts.import_prompt_corpus import (
    corpus_row_to_prompt_example,
    external_id_tag,
    is_already_imported,
    read_corpus_rows,
)

TEMPLATE = Path("data/templates/prompt-corpus-v1.csv")


def test_template_rows_are_read_with_stripped_text() -> None:
    rows = read_corpus_rows(TEMPLATE)

    assert len(rows) == 2
    assert rows[0]["external_id"] == "example-001"
    assert rows[0]["project_slug"] == "example-project"
    assert rows[1]["status"] == "rejected"


def test_approved_row_maps_to_persistence_input() -> None:
    row = read_corpus_rows(TEMPLATE)[0]
    project_id = uuid4()

    example = corpus_row_to_prompt_example(
        row, project_id=project_id, project_name="Example Project"
    )

    assert example.project_id == project_id
    assert example.base_prompt == "Preserve the character face and cobalt dress."
    assert example.expected_result == "Editorial portrait with consistent identity."
    assert example.generated_image_description == "Neutral studio portrait."
    assert example.query_type is QueryType.AI_INFLUENCER
    assert example.status is GenerationStatus.APPROVED
    assert example.rejection_reason is None
    assert example.generation_method == "image"
    assert example.target_platform == "web"
    assert example.tags == ["identity", "outfit", "editorial", "external-id:example-001"]
    assert "Preserve the character face and cobalt dress." in example.embedding_text


def test_rejected_row_keeps_its_rejection_reason() -> None:
    row = read_corpus_rows(TEMPLATE)[1]

    example = corpus_row_to_prompt_example(row, project_id=uuid4(), project_name="Example Project")

    assert example.status is GenerationStatus.REJECTED
    assert example.rejection_reason == "Wardrobe changed between frames."
    assert example.tags == ["continuity", "wardrobe", "external-id:example-002"]


def test_reimport_is_detected_by_external_id_or_prompt() -> None:
    row = read_corpus_rows(TEMPLATE)[0]

    assert is_already_imported(set(), {"example-001"}, row) is True
    assert (
        is_already_imported({"Preserve the character face and cobalt dress."}, set(), row) is True
    )
    assert is_already_imported(set(), set(), row) is False
    assert external_id_tag("example-001") == "external-id:example-001"


def test_reading_a_corpus_without_required_columns_fails() -> None:
    import pytest

    with pytest.raises(ValueError, match="Missing required columns"):
        read_corpus_rows(Path("tests/fixtures/corpus/missing-columns.csv"))
