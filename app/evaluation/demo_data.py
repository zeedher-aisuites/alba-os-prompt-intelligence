"""Deterministic 64-example retrieval demonstration dataset."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.enums import GenerationStatus, QueryType

DEMO_PROJECT_NAME = "Alba Retrieval Evaluation Lab"
DEMO_PROJECT_SLUG = "retrieval-evaluation-lab"


@dataclass(frozen=True, slots=True)
class FailurePattern:
    """One explicit counterexample pattern."""

    key: str
    description: str


@dataclass(frozen=True, slots=True)
class CategoryBlueprint:
    """Content vocabulary used to build eight examples for one query type."""

    query_type: QueryType
    subject: str
    anchor: str
    composition: str
    detail: str
    platform: str
    method: str
    failures: tuple[FailurePattern, FailurePattern, FailurePattern]


@dataclass(frozen=True, slots=True)
class DemoExampleSpec:
    """Fully resolved deterministic example specification."""

    key: str
    base_prompt: str
    expected_result: str
    generated_image_description: str
    generation_method: str
    target_platform: str
    query_type: QueryType
    status: GenerationStatus
    review_notes: str
    rejection_reason: str | None
    quality_score: Decimal
    tags: tuple[str, ...]


BLUEPRINTS = (
    CategoryBlueprint(
        query_type=QueryType.AI_INFLUENCER,
        subject="a cobalt-dressed virtual host in a premium lounge",
        anchor="the same face, cobalt wardrobe, and shoulder-length dark hairstyle",
        composition="a confident waist-up portrait with clean negative space",
        detail="natural hands, realistic skin texture, and consistent jewelry",
        platform="manual_other",
        method="text_to_image",
        failures=(
            FailurePattern("outfit-changed", "the cobalt dress changed into casual shorts"),
            FailurePattern("identity-inconsistent", "the host's facial identity changed"),
            FailurePattern("hairstyle-altered", "the dark bob became long blonde hair"),
        ),
    ),
    CategoryBlueprint(
        query_type=QueryType.VIDEO_FRAME,
        subject="two travelers crossing a modern station in sequential frames",
        anchor="their wardrobe, screen position, and left-to-right movement",
        composition="a wide tracking frame with stable eyelines and geography",
        detail="coherent limbs, motion, shadows, and background landmarks",
        platform="manual_other",
        method="image_to_image",
        failures=(
            FailurePattern("direction-inverted", "movement reversed from right to left"),
            FailurePattern("continuity-broken", "positions and props jumped between frames"),
            FailurePattern("outfit-changed", "a traveler's jacket changed color and shape"),
        ),
    ),
    CategoryBlueprint(
        query_type=QueryType.MARKETING,
        subject="a premium wellness campaign with a model holding the product",
        anchor="the approved campaign palette, headline hierarchy, and product identity",
        composition="a balanced social campaign layout with readable call to action",
        detail="legible typography, natural hands, and controlled product reflections",
        platform="instagram",
        method="text_to_image",
        failures=(
            FailurePattern("logo-deformed", "the brand wordmark was misspelled and warped"),
            FailurePattern("hands-defective", "the model had fused fingers around the product"),
            FailurePattern("continuity-broken", "campaign colors and packaging changed"),
        ),
    ),
    CategoryBlueprint(
        query_type=QueryType.PRODUCT_BRAND,
        subject="an amber serum bottle on warm limestone",
        anchor="the bottle proportions, amber glass, and exact label placement",
        composition="a centered hero product with restrained luxury lighting",
        detail="readable packaging, realistic glass, and physically coherent reflections",
        platform="ecommerce",
        method="text_to_image",
        failures=(
            FailurePattern("logo-deformed", "the label logo became malformed"),
            FailurePattern("proportions-broken", "the cap and bottle proportions changed"),
            FailurePattern("continuity-broken", "packaging color changed between variants"),
        ),
    ),
    CategoryBlueprint(
        query_type=QueryType.TOON,
        subject="a stylized cobalt explorer character in a forest",
        anchor="the character silhouette, face, outfit, and color palette",
        composition="a clear full-body pose with readable animated staging",
        detail="clean linework, expressive eyes, and correctly drawn hands",
        platform="manual_other",
        method="text_to_image",
        failures=(
            FailurePattern("hands-defective", "the character had extra malformed fingers"),
            FailurePattern("identity-inconsistent", "the face and silhouette changed"),
            FailurePattern("outfit-changed", "the explorer outfit became unrelated armor"),
        ),
    ),
    CategoryBlueprint(
        query_type=QueryType.LOGO,
        subject="a geometric Alba monogram made from two cobalt arcs",
        anchor="the approved geometry, cobalt color, and clean silhouette",
        composition="a centered scalable mark on a plain white field",
        detail="perfect symmetry, even stroke width, and crisp negative space",
        platform="brand_system",
        method="text_to_image",
        failures=(
            FailurePattern("logo-deformed", "the monogram arcs warped into illegible shapes"),
            FailurePattern("symmetry-broken", "the mark lost symmetry and stroke balance"),
            FailurePattern("continuity-broken", "the logo geometry changed across applications"),
        ),
    ),
    CategoryBlueprint(
        query_type=QueryType.ART,
        subject="a surreal cobalt dancer beneath an amber moon",
        anchor="the dancer's identity, cobalt costume, and dreamlike visual language",
        composition="a dynamic diagonal pose with a clear focal hierarchy",
        detail="anatomically coherent hands, feet, fabric, and moonlight",
        platform="gallery_print",
        method="text_to_image",
        failures=(
            FailurePattern("hands-defective", "the dancer had duplicated distorted hands"),
            FailurePattern("identity-inconsistent", "the dancer's face changed completely"),
            FailurePattern("continuity-broken", "costume and moon position changed"),
        ),
    ),
    CategoryBlueprint(
        query_type=QueryType.OTHER,
        subject="a documentary-style workshop scene with one craftsperson",
        anchor="the craftsperson's identity, apron, tools, and workbench",
        composition="an observational medium shot with believable workspace geography",
        detail="natural hands, coherent tools, and consistent practical lighting",
        platform="manual_other",
        method="text_to_image",
        failures=(
            FailurePattern("identity-inconsistent", "the craftsperson became a different person"),
            FailurePattern("hands-defective", "the hands merged with the tools"),
            FailurePattern("continuity-broken", "the apron and tool layout changed"),
        ),
    ),
)


def _tags(
    blueprint: CategoryBlueprint,
    *,
    role: str,
    key: str,
) -> tuple[str, ...]:
    return (
        "retrieval-demo",
        f"demo-key:{blueprint.query_type.value}-{role}-{key}",
        f"category:{blueprint.query_type.value}",
        f"role:{role}",
        f"relevant:{blueprint.query_type.value}:{role}:{key}",
    )


def _approved_examples(blueprint: CategoryBlueprint) -> tuple[DemoExampleSpec, ...]:
    scenarios = (
        (
            "consistency",
            f"Create {blueprint.subject}; preserve {blueprint.anchor}.",
            f"The result preserves {blueprint.anchor}.",
        ),
        (
            "composition",
            f"Compose {blueprint.subject} using {blueprint.composition}.",
            f"The result delivers {blueprint.composition}.",
        ),
        (
            "detail",
            f"Render {blueprint.subject} with {blueprint.detail}.",
            f"The result shows {blueprint.detail}.",
        ),
    )
    return tuple(
        DemoExampleSpec(
            key=f"{blueprint.query_type.value}-approved-{key}",
            base_prompt=prompt,
            expected_result=expected,
            generated_image_description=f"Approved example: {expected}",
            generation_method=blueprint.method,
            target_platform=blueprint.platform,
            query_type=blueprint.query_type,
            status=GenerationStatus.APPROVED,
            review_notes="Human review confirmed prompt adherence and visual coherence.",
            rejection_reason=None,
            quality_score=Decimal("0.900"),
            tags=_tags(blueprint, role="approved", key=key),
        )
        for key, prompt, expected in scenarios
    )


def _review_examples(blueprint: CategoryBlueprint) -> tuple[DemoExampleSpec, ...]:
    scenarios = (
        (
            "variant",
            f"Produce a restrained alternate view of {blueprint.subject} while retaining "
            f"{blueprint.anchor}.",
        ),
        (
            "detail-check",
            f"Refine {blueprint.subject}; verify {blueprint.detail} before approval.",
        ),
    )
    return tuple(
        DemoExampleSpec(
            key=f"{blueprint.query_type.value}-review-{key}",
            base_prompt=prompt,
            expected_result=f"A plausible result awaiting final review of {blueprint.anchor}.",
            generated_image_description="Candidate output requires a final human comparison.",
            generation_method=blueprint.method,
            target_platform=blueprint.platform,
            query_type=blueprint.query_type,
            status=GenerationStatus.IN_REVIEW,
            review_notes="Pending detailed human validation.",
            rejection_reason=None,
            quality_score=Decimal("0.600"),
            tags=_tags(blueprint, role="review", key=key),
        )
        for key, prompt in scenarios
    )


def _rejected_examples(blueprint: CategoryBlueprint) -> tuple[DemoExampleSpec, ...]:
    return tuple(
        DemoExampleSpec(
            key=f"{blueprint.query_type.value}-failure-{failure.key}",
            base_prompt=(
                f"Generate {blueprint.subject} while preserving {blueprint.anchor} "
                f"and {blueprint.detail}."
            ),
            expected_result=(
                f"The output should preserve {blueprint.anchor} without "
                f"{failure.key.replace('-', ' ')}."
            ),
            generated_image_description=f"Rejected example: {failure.description}.",
            generation_method=blueprint.method,
            target_platform=blueprint.platform,
            query_type=blueprint.query_type,
            status=GenerationStatus.REJECTED,
            review_notes=f"Human review detected {failure.key.replace('-', ' ')}.",
            rejection_reason=failure.description.capitalize() + ".",
            quality_score=Decimal("0.200"),
            tags=(
                *_tags(blueprint, role="failure", key=failure.key),
                f"failure:{failure.key}",
            ),
        )
        for failure in blueprint.failures
    )


def demo_example_specs() -> tuple[DemoExampleSpec, ...]:
    """Return exactly eight deterministic examples for each query type."""
    examples: list[DemoExampleSpec] = []
    for blueprint in BLUEPRINTS:
        examples.extend(_approved_examples(blueprint))
        examples.extend(_review_examples(blueprint))
        examples.extend(_rejected_examples(blueprint))
    return tuple(examples)
