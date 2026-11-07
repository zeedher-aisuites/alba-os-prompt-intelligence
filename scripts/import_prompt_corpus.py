"""Import a validated prompt-corpus CSV into one existing project.

The v1 CSV contract has no dedicated external-identity column in PostgreSQL,
so the importer is idempotent by the same natural key the seeds use
(project plus base prompt) and also by the ``external-id:<id>`` tag it
records on every imported example. ``source_reference`` and ``created_at``
have no storage column and are reported as not stored, never silently
rewritten into another field. Imported examples have no embedding until
``scripts/rebuild_embeddings.py`` runs; the importer never generates one.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from app.core.config import get_settings
from app.db.repositories import ProjectRepository, PromptExampleRepository
from app.db.session import Database
from app.domain.enums import GenerationStatus, QueryType
from app.domain.schemas import PromptExampleCreate
from app.embeddings.builder import EmbeddingTextBuilder, EmbeddingTextSource

from scripts.validate_prompt_corpus import (
    REQUIRED_COLUMNS,
    _normalise_tags,
    validate_corpus,
)

NOT_STORED_FIELDS: tuple[str, ...] = ("source_reference", "created_at")


def external_id_tag(external_id: str) -> str:
    """Return the provenance tag recorded for one imported external ID."""
    return f"external-id:{external_id.strip()}"


def read_corpus_rows(path: Path) -> list[dict[str, str]]:
    """Read validated CSV rows as stripped text, without touching a database."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        missing = [column for column in REQUIRED_COLUMNS if column not in headers]
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(missing)}.")
        return [
            {column: str(source.get(column) or "").strip() for column in REQUIRED_COLUMNS}
            for source in reader
        ]


def corpus_row_to_prompt_example(
    row: dict[str, str],
    *,
    project_id: UUID,
    project_name: str,
) -> PromptExampleCreate:
    """Map one validated CSV row to persistence input, without writing it."""
    tags = [*_normalise_tags(row["tags"]), external_id_tag(row["external_id"])]
    document = EmbeddingTextBuilder().build(
        EmbeddingTextSource(
            project=project_name,
            query_type=QueryType(row["query_type"]),
            expected_result=row["expected_result"],
            generated_image_description=row["result_description"] or None,
            base_prompt=row["prompt"],
            generation_method=row["generation_method"],
            target_platform=row["platform"],
            status=GenerationStatus(row["status"]),
            review_notes=row["review_notes"] or None,
            rejection_reason=row["rejection_reason"] or None,
            tags=tuple(tags),
        )
    )
    return PromptExampleCreate(
        project_id=project_id,
        base_prompt=row["prompt"],
        expected_result=row["expected_result"],
        generated_image_description=row["result_description"] or None,
        generation_method=row["generation_method"],
        target_platform=row["platform"],
        query_type=QueryType(row["query_type"]),
        status=GenerationStatus(row["status"]),
        review_notes=row["review_notes"] or None,
        rejection_reason=row["rejection_reason"] or None,
        quality_score=None,
        tags=tags,
        embedding_text=document.text,
    )


def is_already_imported(
    existing_prompts: set[str],
    existing_external_ids: set[str],
    row: dict[str, str],
) -> bool:
    """Detect a re-import by prompt text or by the recorded external ID."""
    return row["prompt"] in existing_prompts or row["external_id"] in existing_external_ids


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Observable idempotent import result."""

    project: str
    rows_read: int
    created: int
    existing: int
    dry_run: bool
    database_written: bool
    embeddings_generated: bool
    not_stored_fields: tuple[str, ...] = NOT_STORED_FIELDS


def parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse one explicit CSV import request."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="UTF-8 CSV file to import")
    parser.add_argument(
        "--project",
        required=True,
        help="Existing project slug; every CSV row must use this slug",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report what would be imported without writing",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat validation warnings as a failed import",
    )
    return parser.parse_args(arguments)


async def import_corpus(
    csv_path: Path,
    *,
    project_slug: str,
    dry_run: bool,
    strict: bool,
) -> ImportResult:
    """Validate, then insert only the rows that are not already imported."""
    report = cast(dict[str, Any], validate_corpus(csv_path))
    if int(report["error_count"]) > 0 or (strict and int(report["warning_count"]) > 0):
        print(json.dumps(report, indent=2, sort_keys=True))
        raise SystemExit(1)

    rows = read_corpus_rows(csv_path)
    mismatched = sorted({row["project_slug"] for row in rows} - {project_slug})
    if mismatched:
        print(
            json.dumps(
                {
                    "error_code": "PROJECT_SLUG_MISMATCH",
                    "message": (
                        f"Every row must use project '{project_slug}'; "
                        f"found: {', '.join(mismatched)}."
                    ),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)

    database = Database(get_settings())
    try:
        async with database.transaction() as session:
            projects = ProjectRepository(session)
            examples = PromptExampleRepository(session)
            project = await projects.get_by_slug(project_slug)
            if project is None:
                print(
                    json.dumps(
                        {
                            "error_code": "PROJECT_NOT_FOUND",
                            "message": (
                                f"Project '{project_slug}' does not exist. "
                                "Seed it first or use an existing project slug."
                            ),
                        },
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                )
                raise SystemExit(1)

            existing_prompts: set[str] = set()
            existing_external_ids: set[str] = set()
            offset = 0
            while True:
                page = await examples.list_by_project(project.id, offset=offset, limit=100)
                if not page:
                    break
                for example in page:
                    existing_prompts.add(example.base_prompt)
                    for tag in example.tags:
                        if tag.startswith("external-id:"):
                            existing_external_ids.add(tag.removeprefix("external-id:"))
                offset += len(page)

            created = 0
            existing = 0
            for row in rows:
                if is_already_imported(existing_prompts, existing_external_ids, row):
                    existing += 1
                    continue
                if not dry_run:
                    await examples.create(
                        corpus_row_to_prompt_example(
                            row,
                            project_id=project.id,
                            project_name=project.name,
                        )
                    )
                existing_prompts.add(row["prompt"])
                existing_external_ids.add(row["external_id"])
                created += 1
    finally:
        await database.dispose()

    return ImportResult(
        project=project_slug,
        rows_read=len(rows),
        created=created,
        existing=existing,
        dry_run=dry_run,
        database_written=not dry_run and created > 0,
        embeddings_generated=False,
    )


async def main(arguments: Sequence[str] | None = None) -> int:
    """Run one import and print a JSON summary."""
    args = parse_args(arguments)
    result = await import_corpus(
        args.csv_path,
        project_slug=args.project,
        dry_run=args.dry_run,
        strict=args.strict,
    )
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
