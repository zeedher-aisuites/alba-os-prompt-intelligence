"""Typed errors for durable workflow operations."""

from __future__ import annotations

from app.core.exceptions import AlbaError, ErrorDetail


class WorkflowNotFoundError(AlbaError):
    """Raised when no checkpoint exists for a thread."""

    def __init__(self, thread_id: str) -> None:
        super().__init__(
            ErrorDetail(
                error_code="WORKFLOW_NOT_FOUND",
                message=f"Workflow thread '{thread_id}' was not found.",
            )
        )


class WorkflowAlreadyExistsError(AlbaError):
    """Raised when start is called for an existing durable thread."""

    def __init__(self, thread_id: str) -> None:
        super().__init__(
            ErrorDetail(
                error_code="WORKFLOW_ALREADY_EXISTS",
                message=f"Workflow thread '{thread_id}' already exists.",
            )
        )


class WorkflowNotWaitingError(AlbaError):
    """Raised when a resume command targets a non-paused workflow."""

    def __init__(self, thread_id: str, phase: str) -> None:
        super().__init__(
            ErrorDetail(
                error_code="WORKFLOW_NOT_WAITING",
                message=(f"Workflow thread '{thread_id}' cannot resume while in phase '{phase}'."),
            )
        )


class WorkflowRevisionLimitError(AlbaError):
    """Raised before checkpoint mutation when the one-revision limit is reached."""

    def __init__(self, thread_id: str) -> None:
        super().__init__(
            ErrorDetail(
                error_code="WORKFLOW_REVISION_LIMIT",
                message=f"Workflow thread '{thread_id}' already used its single revision.",
            )
        )


class WorkflowStateError(AlbaError):
    """Raised when persisted workflow state is internally inconsistent."""

    def __init__(self, message: str) -> None:
        super().__init__(
            ErrorDetail(
                error_code="WORKFLOW_STATE_INVALID",
                message=message,
            )
        )


class WorkflowCheckpointUnavailableError(AlbaError):
    """Raised when checkpoint storage is unavailable or uninitialized."""

    def __init__(self) -> None:
        super().__init__(
            ErrorDetail(
                error_code="WORKFLOW_CHECKPOINT_UNAVAILABLE",
                message="The durable workflow checkpoint store is unavailable.",
                retryable=True,
            )
        )


class WorkflowCheckpointSchemaMissingError(AlbaError):
    """Raised when saver setup is attempted before the Alembic migration."""

    def __init__(self) -> None:
        super().__init__(
            ErrorDetail(
                error_code="WORKFLOW_CHECKPOINT_SCHEMA_MISSING",
                message=(
                    "The workflow checkpoint schema is missing; "
                    "run Alembic upgrade before checkpointer setup."
                ),
            )
        )
