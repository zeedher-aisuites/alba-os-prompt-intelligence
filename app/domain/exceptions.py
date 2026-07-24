"""Typed failures raised by persistence use cases."""

from __future__ import annotations

from uuid import UUID

from app.core.exceptions import AlbaError, ErrorDetail


class EntityNotFoundError(AlbaError):
    """Raised when a requested persistent entity does not exist."""

    def __init__(self, entity: str, identifier: UUID | str) -> None:
        super().__init__(
            ErrorDetail(
                error_code="ENTITY_NOT_FOUND",
                message=f"{entity} '{identifier}' was not found.",
            )
        )


class DuplicateSlugError(AlbaError):
    """Raised when a project slug conflicts with an existing project."""

    def __init__(self, slug: str) -> None:
        super().__init__(
            ErrorDetail(
                error_code="DUPLICATE_PROJECT_SLUG",
                message=f"A project with slug '{slug}' already exists.",
            )
        )


class ConstraintViolationError(AlbaError):
    """Raised when persisted data violates a database invariant."""

    def __init__(self, entity: str) -> None:
        super().__init__(
            ErrorDetail(
                error_code="CONSTRAINT_VIOLATION",
                message=f"The {entity} data violates a persistence constraint.",
            )
        )


class ResourceInUseError(AlbaError):
    """Raised when deletion is blocked by dependent source-of-truth records."""

    def __init__(self, entity: str, identifier: UUID | str) -> None:
        super().__init__(
            ErrorDetail(
                error_code="RESOURCE_IN_USE",
                message=f"{entity} '{identifier}' still has dependent records.",
            )
        )


class DatabaseUnavailableError(AlbaError):
    """Raised when PostgreSQL cannot answer a connectivity probe."""

    def __init__(self) -> None:
        super().__init__(
            ErrorDetail(
                error_code="DATABASE_UNAVAILABLE",
                message="The PostgreSQL persistence service is unavailable.",
                retryable=True,
            )
        )


class InvalidRunTransitionError(AlbaError):
    """Raised when a generation run lifecycle transition is not allowed."""

    def __init__(self, identifier: UUID | str, current: str, target: str) -> None:
        super().__init__(
            ErrorDetail(
                error_code="INVALID_RUN_TRANSITION",
                message=(
                    f"GenerationRun '{identifier}' cannot transition from "
                    f"'{current}' to '{target}'."
                ),
            )
        )
