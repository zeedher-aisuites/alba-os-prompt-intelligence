"""Insert a small deterministic and idempotent Stage 1 dataset."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from uuid import UUID

from app.core.config import get_settings
from app.db.repositories import ProjectRepository, PromptExampleRepository
from app.db.session import Database
from app.domain.enums import GenerationStatus, QueryType
from app.domain.schemas import ProjectCreate, PromptExampleCreate
from app.embeddings.builder import EmbeddingTextBuilder, EmbeddingTextSource


@dataclass(frozen=True, slots=True)
class SeedExample:
    """Template that becomes a PromptExample after its project is resolved."""

    project_slug: str
    base_prompt: str
    expected_result: str
    generated_image_description: str
    generation_method: str
    target_platform: str
    query_type: QueryType
    status: GenerationStatus
    review_notes: str | None
    rejection_reason: str | None
    quality_score: Decimal | None
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SeedResult:
    """Counts that make seed behavior observable and testable."""

    projects_created: int
    projects_existing: int
    examples_created: int
    examples_existing: int


PROJECTS = (
    ProjectCreate(
        name="Cobalt Lounge Campaign",
        slug="cobalt-lounge",
        description="Continuity-focused premium hospitality campaign.",
    ),
    ProjectCreate(
        name="Alba Product Studio",
        slug="alba-product-studio",
        description="Product, marketing, and brand composition experiments.",
    ),
)

EXAMPLES = (
    SeedExample(
        project_slug="cobalt-lounge",
        base_prompt=(
            "Cinematic cobalt host guiding a guest into a premium lounge, moving left to right."
        ),
        expected_result="A coherent entrance frame with stable wardrobe and movement direction.",
        generated_image_description=(
            "The host keeps a cobalt dress while both people enter the lounge."
        ),
        generation_method="text_to_image",
        target_platform="manual_other",
        query_type=QueryType.AI_INFLUENCER,
        status=GenerationStatus.APPROVED,
        review_notes="Strong wardrobe and direction continuity.",
        rejection_reason=None,
        quality_score=Decimal("0.920"),
        tags=("continuity", "hospitality", "cobalt"),
    ),
    SeedExample(
        project_slug="cobalt-lounge",
        base_prompt="Host exits the lounge while the guest follows in the same screen direction.",
        expected_result="Both subjects exit without reversing the established movement.",
        generated_image_description=(
            "The host enters instead of exiting and her skirt becomes shorts."
        ),
        generation_method="text_to_image",
        target_platform="manual_other",
        query_type=QueryType.VIDEO_FRAME,
        status=GenerationStatus.REJECTED,
        review_notes="Action and wardrobe both contradict the brief.",
        rejection_reason="Movement direction reversed and outfit changed.",
        quality_score=Decimal("0.180"),
        tags=("continuity-failure", "outfit-change", "direction"),
    ),
    SeedExample(
        project_slug="cobalt-lounge",
        base_prompt="Close-up continuity frame of the cobalt host greeting a returning guest.",
        expected_result="Stable face, hairstyle, and cobalt wardrobe.",
        generated_image_description="A plausible close-up awaiting identity review.",
        generation_method="image_to_image",
        target_platform="manual_other",
        query_type=QueryType.VIDEO_FRAME,
        status=GenerationStatus.IN_REVIEW,
        review_notes="Manual identity comparison still required.",
        rejection_reason=None,
        quality_score=None,
        tags=("identity", "close-up", "review"),
    ),
    SeedExample(
        project_slug="alba-product-studio",
        base_prompt="Premium serum bottle centered on warm stone with a clean amber rim light.",
        expected_result="Legible packaging, accurate proportions, and restrained luxury lighting.",
        generated_image_description=(
            "Centered product with readable label and controlled reflections."
        ),
        generation_method="text_to_image",
        target_platform="manual_other",
        query_type=QueryType.PRODUCT_BRAND,
        status=GenerationStatus.APPROVED,
        review_notes="Good material rendering and label placement.",
        rejection_reason=None,
        quality_score=Decimal("0.880"),
        tags=("product", "serum", "premium"),
    ),
    SeedExample(
        project_slug="alba-product-studio",
        base_prompt=(
            "Minimal campaign poster with the Alba wordmark above a cobalt product pedestal."
        ),
        expected_result="Balanced negative space and an undeformed wordmark.",
        generated_image_description="The pedestal is balanced but the wordmark is malformed.",
        generation_method="text_to_image",
        target_platform="manual_other",
        query_type=QueryType.MARKETING,
        status=GenerationStatus.REJECTED,
        review_notes="Composition is usable; brand typography is not.",
        rejection_reason="Brand wordmark is deformed.",
        quality_score=Decimal("0.350"),
        tags=("marketing", "logo-failure", "composition"),
    ),
    SeedExample(
        project_slug="alba-product-studio",
        base_prompt="Geometric Alba monogram using two interlocking cobalt arcs on white.",
        expected_result="A simple scalable mark with clean symmetry.",
        generated_image_description="Symmetric cobalt monogram with clear silhouette.",
        generation_method="text_to_image",
        target_platform="manual_other",
        query_type=QueryType.LOGO,
        status=GenerationStatus.IN_REVIEW,
        review_notes="Needs final brand approval.",
        rejection_reason=None,
        quality_score=Decimal("0.740"),
        tags=("logo", "geometric", "cobalt"),
    ),
)


def build_embedding_text(
    *,
    project_name: str,
    example: SeedExample,
) -> str:
    """Build source text now; vector generation remains out of scope."""
    return (
        EmbeddingTextBuilder()
        .build(
            EmbeddingTextSource(
                project=project_name,
                query_type=example.query_type,
                expected_result=example.expected_result,
                generated_image_description=example.generated_image_description,
                base_prompt=example.base_prompt,
                generation_method=example.generation_method,
                target_platform=example.target_platform,
                status=example.status,
                review_notes=example.review_notes,
                rejection_reason=example.rejection_reason,
                tags=example.tags,
            )
        )
        .text
    )


def to_prompt_example(
    template: SeedExample,
    *,
    project_id: UUID,
    project_name: str,
) -> PromptExampleCreate:
    """Resolve a deterministic template into validated persistence input."""
    return PromptExampleCreate(
        project_id=project_id,
        base_prompt=template.base_prompt,
        expected_result=template.expected_result,
        generated_image_description=template.generated_image_description,
        generation_method=template.generation_method,
        target_platform=template.target_platform,
        query_type=template.query_type,
        status=template.status,
        review_notes=template.review_notes,
        rejection_reason=template.rejection_reason,
        quality_score=template.quality_score,
        tags=list(template.tags),
        embedding_text=build_embedding_text(
            project_name=project_name,
            example=template,
        ),
    )


async def seed_database(database: Database) -> SeedResult:
    """Insert the Stage 1 seed once, using slugs and prompts as natural keys."""
    projects_created = 0
    projects_existing = 0
    examples_created = 0
    examples_existing = 0

    async with database.transaction() as session:
        project_repository = ProjectRepository(session)
        example_repository = PromptExampleRepository(session)
        projects_by_slug = {}

        for project_data in PROJECTS:
            project = await project_repository.get_by_slug(project_data.slug)
            if project is None:
                project = await project_repository.create(project_data)
                projects_created += 1
            else:
                projects_existing += 1
            projects_by_slug[project.slug] = project

        existing_prompts_by_project: dict[UUID, set[str]] = {}
        for project in projects_by_slug.values():
            existing = await example_repository.list_by_project(project.id)
            existing_prompts_by_project[project.id] = {example.base_prompt for example in existing}

        for template in EXAMPLES:
            project = projects_by_slug[template.project_slug]
            if template.base_prompt in existing_prompts_by_project[project.id]:
                examples_existing += 1
                continue
            await example_repository.create(
                to_prompt_example(
                    template,
                    project_id=project.id,
                    project_name=project.name,
                )
            )
            existing_prompts_by_project[project.id].add(template.base_prompt)
            examples_created += 1

    return SeedResult(
        projects_created=projects_created,
        projects_existing=projects_existing,
        examples_created=examples_created,
        examples_existing=examples_existing,
    )


async def main() -> None:
    """Run the deterministic seed from the command line."""
    database = Database(get_settings())
    try:
        result = await seed_database(database)
        print(json.dumps(asdict(result), sort_keys=True))
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
