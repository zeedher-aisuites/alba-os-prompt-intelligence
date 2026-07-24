"""Twenty deterministic retrieval evaluation cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.domain.enums import QueryType


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    """One query with a server-resolved relevance tag."""

    key: str
    retrieval_kind: Literal["approved", "failure"]
    query: str
    query_type: QueryType
    relevant_tag: str


EVALUATION_CASES: tuple[EvaluationCase, ...] = (
    EvaluationCase(
        "positive-influencer-consistency",
        "approved",
        "Keep the virtual host face, cobalt outfit, and dark hairstyle consistent.",
        QueryType.AI_INFLUENCER,
        "relevant:ai_influencer:approved:consistency",
    ),
    EvaluationCase(
        "positive-influencer-detail",
        "approved",
        "Create realistic skin, natural hands, and consistent jewelry for the host.",
        QueryType.AI_INFLUENCER,
        "relevant:ai_influencer:approved:detail",
    ),
    EvaluationCase(
        "positive-video-direction",
        "approved",
        "Maintain traveler wardrobe and left-to-right movement across station frames.",
        QueryType.VIDEO_FRAME,
        "relevant:video_frame:approved:consistency",
    ),
    EvaluationCase(
        "positive-video-composition",
        "approved",
        "Use a wide tracking frame with stable eyelines and geography.",
        QueryType.VIDEO_FRAME,
        "relevant:video_frame:approved:composition",
    ),
    EvaluationCase(
        "positive-marketing-layout",
        "approved",
        "Create a balanced social campaign layout with readable call to action.",
        QueryType.MARKETING,
        "relevant:marketing:approved:composition",
    ),
    EvaluationCase(
        "positive-product-detail",
        "approved",
        "Render readable serum packaging, realistic amber glass, and reflections.",
        QueryType.PRODUCT_BRAND,
        "relevant:product_brand:approved:detail",
    ),
    EvaluationCase(
        "positive-toon-consistency",
        "approved",
        "Preserve the explorer silhouette, face, outfit, and palette.",
        QueryType.TOON,
        "relevant:toon:approved:consistency",
    ),
    EvaluationCase(
        "positive-logo-symmetry",
        "approved",
        "Create symmetric cobalt arcs with even stroke and crisp negative space.",
        QueryType.LOGO,
        "relevant:logo:approved:detail",
    ),
    EvaluationCase(
        "positive-art-composition",
        "approved",
        "Compose the cobalt dancer in a dynamic diagonal pose with clear focal hierarchy.",
        QueryType.ART,
        "relevant:art:approved:composition",
    ),
    EvaluationCase(
        "positive-other-workshop",
        "approved",
        "Keep the craftsperson, apron, tools, and workbench consistent.",
        QueryType.OTHER,
        "relevant:other:approved:consistency",
    ),
    EvaluationCase(
        "failure-outfit-change",
        "failure",
        "Find examples where the virtual host's cobalt outfit changed unexpectedly.",
        QueryType.AI_INFLUENCER,
        "relevant:ai_influencer:failure:outfit-changed",
    ),
    EvaluationCase(
        "failure-identity",
        "failure",
        "Find a rejected virtual host example with inconsistent facial identity.",
        QueryType.AI_INFLUENCER,
        "relevant:ai_influencer:failure:identity-inconsistent",
    ),
    EvaluationCase(
        "failure-hairstyle",
        "failure",
        "Find a host whose dark hairstyle changed to long blonde hair.",
        QueryType.AI_INFLUENCER,
        "relevant:ai_influencer:failure:hairstyle-altered",
    ),
    EvaluationCase(
        "failure-direction",
        "failure",
        "Find sequential frames where travel direction reversed.",
        QueryType.VIDEO_FRAME,
        "relevant:video_frame:failure:direction-inverted",
    ),
    EvaluationCase(
        "failure-continuity",
        "failure",
        "Find station frames with broken positions, props, and continuity.",
        QueryType.VIDEO_FRAME,
        "relevant:video_frame:failure:continuity-broken",
    ),
    EvaluationCase(
        "failure-marketing-hands",
        "failure",
        "Find a campaign image where fingers fused around the product.",
        QueryType.MARKETING,
        "relevant:marketing:failure:hands-defective",
    ),
    EvaluationCase(
        "failure-product-logo",
        "failure",
        "Find a rejected serum package with a malformed label logo.",
        QueryType.PRODUCT_BRAND,
        "relevant:product_brand:failure:logo-deformed",
    ),
    EvaluationCase(
        "failure-toon-hands",
        "failure",
        "Find the cartoon explorer with extra malformed fingers.",
        QueryType.TOON,
        "relevant:toon:failure:hands-defective",
    ),
    EvaluationCase(
        "failure-logo-deformation",
        "failure",
        "Find a deformed monogram with warped illegible arcs.",
        QueryType.LOGO,
        "relevant:logo:failure:logo-deformed",
    ),
    EvaluationCase(
        "failure-art-continuity",
        "failure",
        "Find the artwork where costume and moon position changed.",
        QueryType.ART,
        "relevant:art:failure:continuity-broken",
    ),
)
