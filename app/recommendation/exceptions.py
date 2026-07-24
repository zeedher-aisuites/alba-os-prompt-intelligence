"""Typed failures for structured recommendation."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID


class RecommendationError(Exception):
    """Base error with a stable code safe to persist."""

    error_code = "RECOMMENDATION_FAILED"


class RecommendationContextError(RecommendationError):
    """Raised when bounded safe context cannot be constructed."""

    error_code = "RECOMMENDATION_CONTEXT_INVALID"


class RecommendationContextBudgetError(RecommendationContextError):
    """Raised when critical request data cannot fit without truncation."""

    error_code = "RECOMMENDATION_CONTEXT_BUDGET_EXCEEDED"


class RecommendationProviderUnavailableError(RecommendationError):
    """Raised when the configured local chat provider cannot answer."""

    error_code = "RECOMMENDATION_PROVIDER_UNAVAILABLE"


class RecommendationResponseValidationError(RecommendationError):
    """Raised after structured output and its one repair attempt both fail."""

    error_code = "RECOMMENDATION_RESPONSE_INVALID"


class RecommendationModelMismatchError(RecommendationError):
    """Raised when the provider reports a model other than the configured one."""

    error_code = "RECOMMENDATION_MODEL_MISMATCH"


class FabricatedEvidenceReferenceError(RecommendationError):
    """Raised when provider output references evidence outside the safe context."""

    error_code = "FABRICATED_EVIDENCE_REFERENCE"

    def __init__(self, identifiers: Iterable[UUID]) -> None:
        joined = ", ".join(sorted(str(identifier) for identifier in identifiers))
        super().__init__(f"Recommendation referenced unavailable evidence IDs: {joined}.")


class EvidenceStatusMismatchError(RecommendationError):
    """Raised when approved and rejected evidence roles are crossed."""

    error_code = "EVIDENCE_STATUS_MISMATCH"


class MissingPositiveEvidenceCitationError(RecommendationError):
    """Raised when retrieved approved evidence is not cited by the provider."""

    error_code = "POSITIVE_EVIDENCE_CITATION_MISSING"


class FabricatedConstraintReferenceError(RecommendationError):
    """Raised when provider output references a constraint outside the request."""

    error_code = "FABRICATED_CONSTRAINT_REFERENCE"

    def __init__(self, identifiers: Iterable[str]) -> None:
        joined = ", ".join(sorted(identifiers))
        super().__init__(f"Recommendation referenced unavailable constraint IDs: {joined}.")


class ConstraintAccountingError(RecommendationError):
    """Raised when request constraints are missing or counted more than once."""

    error_code = "CONSTRAINT_ACCOUNTING_INVALID"
