"""Insert the separate deterministic 64-example retrieval dataset."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from uuid import UUID

from app.core.config import get_settings
from app.db.repositories import ProjectRepository, PromptExampleRepository
from app.db.session import Database
from app.domain.schemas import ProjectCreate, PromptExampleCreate
from app.embeddings.builder import EmbeddingTextBuilder, EmbeddingTextSource
from app.evaluation.demo_data import (
    DEMO_PROJECT_NAME,
    DEMO_PROJECT_SLUG,
    DemoExampleSpec,
    demo_example_specs,
)


@dataclass(frozen=True, slots=True)
class DemoSeedResult:
    """Observable idempotent demo-seed result."""

    projects_created: int
    projects_existing: int
    examples_created: int
    examples_existing: int


def _example_input(
    spec: DemoExampleSpec,
    *,
    project_id: UUID,
    project_name: str,
) -> PromptExampleCreate:
    document = EmbeddingTextBuilder().build(
        EmbeddingTextSource(
            project=project_name,
            query_type=spec.query_type,
            expected_result=spec.expected_result,
            generated_image_description=spec.generated_image_description,
            base_prompt=spec.base_prompt,
            generation_method=spec.generation_method,
            target_platform=spec.target_platform,
            status=spec.status,
            review_notes=spec.review_notes,
            rejection_reason=spec.rejection_reason,
            tags=spec.tags,
        )
    )
    return PromptExampleCreate(
        project_id=project_id,
        base_prompt=spec.base_prompt,
        expected_result=spec.expected_result,
        generated_image_description=spec.generated_image_description,
        generation_method=spec.generation_method,
        target_platform=spec.target_platform,
        query_type=spec.query_type,
        status=spec.status,
        review_notes=spec.review_notes,
        rejection_reason=spec.rejection_reason,
        quality_score=spec.quality_score,
        tags=list(spec.tags),
        embedding_text=document.text,
    )


async def seed_retrieval_demo(database: Database) -> DemoSeedResult:
    """Insert all demo records once, keyed by deterministic tags."""
    projects_created = 0
    projects_existing = 0
    examples_created = 0
    examples_existing = 0
    specs = demo_example_specs()

    async with database.transaction() as session:
        projects = ProjectRepository(session)
        examples = PromptExampleRepository(session)
        project = await projects.get_by_slug(DEMO_PROJECT_SLUG)
        if project is None:
            project = await projects.create(
                ProjectCreate(
                    name=DEMO_PROJECT_NAME,
                    slug=DEMO_PROJECT_SLUG,
                    description=(
                        "Deterministic synthetic evidence for exact retrieval evaluation."
                    ),
                )
            )
            projects_created = 1
        else:
            projects_existing = 1

        existing = await examples.list_by_project(project.id, limit=100)
        existing_keys = {
            tag.removeprefix("demo-key:")
            for example in existing
            for tag in example.tags
            if tag.startswith("demo-key:")
        }
        for spec in specs:
            if spec.key in existing_keys:
                examples_existing += 1
                continue
            await examples.create(
                _example_input(
                    spec,
                    project_id=project.id,
                    project_name=project.name,
                )
            )
            examples_created += 1
            existing_keys.add(spec.key)

    return DemoSeedResult(
        projects_created=projects_created,
        projects_existing=projects_existing,
        examples_created=examples_created,
        examples_existing=examples_existing,
    )


async def main() -> None:
    """Run the demo seed against the development database."""
    database = Database(get_settings())
    try:
        result = await seed_retrieval_demo(database)
        print(json.dumps(asdict(result), sort_keys=True))
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
