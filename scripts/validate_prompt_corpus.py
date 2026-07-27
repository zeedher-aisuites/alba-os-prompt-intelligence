"""Validate a user-owned prompt corpus CSV without writing to PostgreSQL."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.domain.enums import GenerationStatus, QueryType

REQUIRED_COLUMNS = (
    "external_id",
    "project_slug",
    "query_type",
    "prompt",
    "expected_result",
    "result_description",
    "status",
    "rejection_reason",
    "review_notes",
    "platform",
    "generation_method",
    "tags",
    "source_reference",
    "created_at",
)
OPTIONAL_COLUMNS = {
    "result_description",
    "rejection_reason",
    "review_notes",
    "source_reference",
    "created_at",
}
MAXIMUM_LENGTHS = {
    "external_id": 120,
    "project_slug": 120,
    "prompt": 16_000,
    "expected_result": 16_000,
    "result_description": 12_000,
    "rejection_reason": 2_000,
    "review_notes": 8_000,
    "platform": 100,
    "generation_method": 100,
    "source_reference": 1_000,
    "tag": 80,
}


@dataclass(frozen=True)
class Issue:
    """A concise, spreadsheet-addressable validation finding."""

    row: int
    field: str
    code: str
    message: str

    def as_json(self) -> dict[str, object]:
        return {
            "row": self.row,
            "field": self.field,
            "code": self.code,
            "message": self.message,
        }


def parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse a read-only CSV validation request."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="UTF-8 CSV file to inspect")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat normalization warnings as a non-zero validation result.",
    )
    return parser.parse_args(arguments)


def validate_corpus(path: Path) -> dict[str, object]:
    """Return a JSON-safe report while leaving the input and databases untouched."""
    errors: list[Issue] = []
    warnings: list[Issue] = []
    normalized_tags: dict[str, list[str]] = {}
    seen_external_ids: dict[str, int] = {}
    seen_rows: dict[str, int] = {}
    rows_read = 0

    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        return _report(
            path,
            rows_read=0,
            valid_rows=0,
            errors=[Issue(0, "file", "FILE_UNREADABLE", str(exc))],
            warnings=[],
            normalized_tags={},
        )

    with handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        missing = [column for column in REQUIRED_COLUMNS if column not in headers]
        unexpected = [column for column in headers if column not in REQUIRED_COLUMNS]
        for column in missing:
            errors.append(Issue(1, column, "MISSING_COLUMN", "Required column is missing."))
        for column in unexpected:
            warnings.append(Issue(1, column, "UNKNOWN_COLUMN", "Column is ignored by v1."))
        if missing:
            return _report(
                path,
                rows_read=0,
                valid_rows=0,
                errors=errors,
                warnings=warnings,
                normalized_tags={},
            )

        for row_number, source in enumerate(reader, start=2):
            rows_read += 1
            row = {column: _normalise_text(source.get(column)) for column in REQUIRED_COLUMNS}
            row_errors, row_warnings, tags = _validate_row(row_number, row)
            errors.extend(row_errors)
            warnings.extend(row_warnings)
            normalized_tags[str(row_number)] = tags

            external_id = row["external_id"]
            if external_id:
                duplicate_row = seen_external_ids.setdefault(external_id, row_number)
                if duplicate_row != row_number:
                    errors.append(
                        Issue(
                            row_number,
                            "external_id",
                            "DUPLICATE_EXTERNAL_ID",
                            f"First used on row {duplicate_row}.",
                        )
                    )

            fingerprint = _row_fingerprint(row, tags)
            duplicate_row = seen_rows.setdefault(fingerprint, row_number)
            if duplicate_row != row_number:
                errors.append(
                    Issue(
                        row_number,
                        "row",
                        "DUPLICATE_ROW",
                        f"Same normalized content as row {duplicate_row}.",
                    )
                )

    valid_rows = rows_read - len({issue.row for issue in errors if issue.row >= 2})
    return _report(
        path,
        rows_read=rows_read,
        valid_rows=max(0, valid_rows),
        errors=errors,
        warnings=warnings,
        normalized_tags=normalized_tags,
    )


def _validate_row(
    row_number: int,
    row: dict[str, str],
) -> tuple[list[Issue], list[Issue], list[str]]:
    errors: list[Issue] = []
    warnings: list[Issue] = []
    for field in REQUIRED_COLUMNS:
        if field not in OPTIONAL_COLUMNS and not row[field]:
            errors.append(Issue(row_number, field, "REQUIRED", "A value is required."))
    for field, maximum in MAXIMUM_LENGTHS.items():
        if field == "tag":
            continue
        if len(row[field]) > maximum:
            errors.append(
                Issue(row_number, field, "TOO_LONG", f"Maximum length is {maximum} characters.")
            )
    if row["project_slug"] and not _is_slug(row["project_slug"]):
        errors.append(
            Issue(row_number, "project_slug", "INVALID_SLUG", "Use lowercase kebab-case.")
        )
    if row["query_type"] and row["query_type"] not in {item.value for item in QueryType}:
        errors.append(
            Issue(row_number, "query_type", "INVALID_QUERY_TYPE", "Unsupported query type.")
        )
    if row["status"] and row["status"] not in {item.value for item in GenerationStatus}:
        errors.append(
            Issue(row_number, "status", "INVALID_STATUS", "Unsupported generation status.")
        )
    if row["created_at"]:
        try:
            parsed = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timezone is required")
        except ValueError:
            errors.append(
                Issue(
                    row_number,
                    "created_at",
                    "INVALID_TIMESTAMP",
                    "Use an ISO-8601 UTC timestamp.",
                )
            )
    tags = _normalise_tags(row["tags"])
    if len(tags) != len([value for value in row["tags"].split("|") if value.strip()]):
        warnings.append(
            Issue(row_number, "tags", "DUPLICATE_TAG", "Duplicate tags were normalized.")
        )
    for tag in tags:
        if len(tag) > MAXIMUM_LENGTHS["tag"]:
            errors.append(
                Issue(
                    row_number,
                    "tags",
                    "TAG_TOO_LONG",
                    "Each tag is limited to 80 characters.",
                )
            )
    if row["status"] != GenerationStatus.REJECTED.value and row["rejection_reason"]:
        warnings.append(
            Issue(
                row_number,
                "rejection_reason",
                "UNEXPECTED_REJECTION_REASON",
                "Only rejected examples normally need a rejection reason.",
            )
        )
    return errors, warnings, tags


def _normalise_text(value: object) -> str:
    return str(value or "").strip()


def _normalise_tags(raw: str) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for tag in raw.split("|"):
        normalized = tag.strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            tags.append(normalized)
            seen.add(key)
    return tags


def _is_slug(value: str) -> bool:
    parts = value.split("-")
    return bool(value) and all(part.isalnum() and part == part.lower() for part in parts)


def _row_fingerprint(row: dict[str, str], tags: Iterable[str]) -> str:
    fields = [
        "|".join(tag.casefold() for tag in tags) if field == "tags" else row[field]
        for field in REQUIRED_COLUMNS
        if field != "external_id"
    ]
    payload = "\x1f".join(fields)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _report(
    path: Path,
    *,
    rows_read: int,
    valid_rows: int,
    errors: list[Issue],
    warnings: list[Issue],
    normalized_tags: dict[str, list[str]],
) -> dict[str, object]:
    return {
        "schema": "prompt-corpus-v1",
        "path": str(path),
        "rows_read": rows_read,
        "valid_rows": valid_rows,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": [issue.as_json() for issue in errors],
        "warnings": [issue.as_json() for issue in warnings],
        "normalized_tags": normalized_tags,
        "database_written": False,
        "embeddings_generated": False,
    }


def main(arguments: Sequence[str] | None = None) -> int:
    """Print the report and return a CI-friendly status without changing input files."""
    args = parse_args(arguments)
    report = validate_corpus(args.csv_path)
    print(json.dumps(report, indent=2, sort_keys=True))
    failures = int(report["error_count"]) > 0
    return 1 if failures or (args.strict and int(report["warning_count"]) > 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
