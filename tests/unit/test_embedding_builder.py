"""Deterministic embedding text and hash tests."""

from __future__ import annotations

from hashlib import sha256

from app.domain.enums import GenerationStatus, QueryType
from app.embeddings.builder import EmbeddingTextBuilder, EmbeddingTextSource


def source() -> EmbeddingTextSource:
    """Build source data with intentionally inconsistent whitespace and tags."""
    return EmbeddingTextSource(
        project="  Cobalt   Lounge\nCampaign ",
        query_type=QueryType.VIDEO_FRAME,
        expected_result=" Stable wardrobe\nand direction. ",
        generated_image_description=None,
        base_prompt=" Host exits\tleft to right. ",
        generation_method=" image_to_image ",
        target_platform=" manual_other ",
        status=GenerationStatus.REJECTED,
        review_notes="  Direction reversed. ",
        rejection_reason=None,
        tags=("zeta", " alpha ", "Beta", "alpha", " "),
    )


def test_builder_is_deterministic_and_hashes_utf8_text() -> None:
    builder = EmbeddingTextBuilder()

    first = builder.build(source())
    second = builder.build(source())

    assert first == second
    assert first.source_hash == sha256(first.text.encode("utf-8")).hexdigest()
    assert len(first.source_hash) == 64


def test_builder_normalizes_whitespace_tags_and_optional_fields() -> None:
    document = EmbeddingTextBuilder().build(source())

    assert "Project:\nCobalt Lounge Campaign" in document.text
    assert "Expected result:\nStable wardrobe and direction." in document.text
    assert "Generated image description:\n\nPrompt:" in document.text
    assert "Rejection reason:\n\nTags:" in document.text
    assert document.text.endswith("Tags:\nalpha, Beta, zeta")
    assert "\t" not in document.text
    assert "  " not in document.text


def test_builder_tag_order_does_not_change_document() -> None:
    original = source()
    reordered = EmbeddingTextSource(
        project=original.project,
        query_type=original.query_type,
        expected_result=original.expected_result,
        generated_image_description=original.generated_image_description,
        base_prompt=original.base_prompt,
        generation_method=original.generation_method,
        target_platform=original.target_platform,
        status=original.status,
        review_notes=original.review_notes,
        rejection_reason=original.rejection_reason,
        tags=tuple(reversed(original.tags)),
    )

    assert EmbeddingTextBuilder().build(original) == EmbeddingTextBuilder().build(reordered)
