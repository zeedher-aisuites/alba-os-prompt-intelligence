"""Unit contracts for shared local-web query parsing and pagination."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.domain.enums import GenerationStatus, QueryType, RunStatus
from app.web.filters import LibraryFilters, WorkflowFilters, filters_for_template
from app.web.pagination import page_url, pagination_navigation
from app.web.schemas import PaginationView
from pydantic import ValidationError


def test_library_filters_turn_all_blank_optional_values_into_none() -> None:
    filters = LibraryFilters.model_validate(
        {
            "project_id": "  ",
            "query_type": "",
            "status": " ",
            "platform": "  ",
            "method": "\t",
            "tag": "\n",
            "text": " ",
            "offset": "",
            "limit": "",
        }
    )

    assert filters == LibraryFilters()


def test_shared_filters_trim_and_casefold_enums_without_loosening_validation() -> None:
    project_id = uuid4()
    filters = LibraryFilters.model_validate(
        {
            "project_id": f"  {project_id}  ",
            "query_type": " AI_INFLUENCER ",
            "status": " APPROVED ",
            "platform": " Instagram ",
        }
    )
    workflow_filters = WorkflowFilters.model_validate(
        {"status": " WAITING_FOR_HUMAN ", "provider": " FAKE ", "waiting": " true "}
    )

    assert filters.project_id == project_id
    assert filters.query_type is QueryType.AI_INFLUENCER
    assert filters.status is GenerationStatus.APPROVED
    assert filters.platform == "instagram"
    assert workflow_filters.status is RunStatus.WAITING_FOR_HUMAN
    assert workflow_filters.provider == "fake"
    assert workflow_filters.waiting is True
    assert filters_for_template(workflow_filters)["waiting"] == "true"
    normalized_facets = LibraryFilters(
        platform="  OpenAI  ",
        method="text_to_image",
        tag="  Identity_Preservation  ",
    )
    assert normalized_facets.platform == "openai"
    assert normalized_facets.method == "text-to-image"
    assert normalized_facets.tag == "identity-preservation"
    with pytest.raises(ValidationError):
        LibraryFilters.model_validate({"status": "not-a-status"})


def test_pagination_links_preserve_filters_and_describe_first_middle_and_last_pages() -> None:
    filters = LibraryFilters(platform="Instagram", tag="Cobalt", limit=2)
    first = pagination_navigation(
        "/library",
        filters,
        PaginationView(offset=0, limit=2, has_more=True),
        item_count=2,
    )
    middle = pagination_navigation(
        "/library",
        filters,
        PaginationView(offset=2, limit=2, has_more=True),
        item_count=2,
    )
    last = pagination_navigation(
        "/library",
        filters,
        PaginationView(offset=4, limit=2, has_more=False),
        item_count=1,
    )

    assert first.previous_url is None
    assert first.next_url == "/library?platform=instagram&tag=cobalt&offset=2&limit=2"
    assert first.range_label == "Results 1-2"
    assert middle.previous_url == "/library?platform=instagram&tag=cobalt&offset=0&limit=2"
    assert middle.next_url == "/library?platform=instagram&tag=cobalt&offset=4&limit=2"
    assert last.previous_url == "/library?platform=instagram&tag=cobalt&offset=2&limit=2"
    assert last.next_url is None
    assert page_url("/library", filters, offset=0).endswith("offset=0&limit=2")
