"""Closed vocabularies used by persistence and application contracts."""

from __future__ import annotations

from enum import StrEnum


class QueryType(StrEnum):
    """Creative request categories understood by Alba OS."""

    AI_INFLUENCER = "ai_influencer"
    TOON = "toon"
    PRODUCT_BRAND = "product_brand"
    MARKETING = "marketing"
    LOGO = "logo"
    VIDEO_FRAME = "video_frame"
    ART = "art"
    OTHER = "other"


class GenerationStatus(StrEnum):
    """Human knowledge-promotion status for an example or review."""

    APPROVED = "approved"
    IN_REVIEW = "in_review"
    REJECTED = "rejected"


class RunStatus(StrEnum):
    """Lifecycle state of a generation run."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_HUMAN = "waiting_for_human"
    COMPLETED = "completed"
    FAILED = "failed"
