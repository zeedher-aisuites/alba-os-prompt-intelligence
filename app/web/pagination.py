"""Stable, filter-preserving pagination links for server-rendered views."""

from __future__ import annotations

from urllib.parse import urlencode

from app.web.filters import BaseFilters
from app.web.schemas import PaginationNavigationView, PaginationView


def page_url(path: str, filters: BaseFilters, *, offset: int) -> str:
    """Encode a local query URL with every active canonical filter preserved."""
    values = filters.model_dump(mode="json", exclude_none=True)
    values["offset"] = offset
    return f"{path}?{urlencode(values)}"


def pagination_navigation(
    path: str,
    filters: BaseFilters,
    pagination: PaginationView,
    *,
    item_count: int,
) -> PaginationNavigationView:
    """Build safe previous/next URLs and a truthful range without a count query."""
    if item_count == 0:
        return PaginationNavigationView(
            previous_url=(
                page_url(path, filters, offset=max(0, pagination.offset - pagination.limit))
                if pagination.offset > 0
                else None
            ),
            next_url=None,
            range_label="No results",
        )
    start = pagination.offset + 1
    end = pagination.offset + item_count
    return PaginationNavigationView(
        previous_url=(
            page_url(path, filters, offset=max(0, pagination.offset - pagination.limit))
            if pagination.offset > 0
            else None
        ),
        next_url=(
            page_url(path, filters, offset=pagination.offset + pagination.limit)
            if pagination.has_more
            else None
        ),
        range_label=f"Results {start}-{end}",
    )
