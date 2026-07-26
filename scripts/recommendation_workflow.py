"""Operate the durable Stage 4 recommendation workflow."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import cast
from uuid import UUID

from app.core.config import get_settings
from app.core.exceptions import AlbaError
from app.db.repositories import GenerationRunRepository, ProjectRepository
from app.db.session import Database
from app.domain.enums import QueryType
from app.domain.exceptions import EntityNotFoundError
from app.recommendation.factory import RecommendationProviderKind
from app.recommendation.schemas import RecommendationRequest
from app.workflow.checkpoint import (
    CHECKPOINT_SCHEMA,
    open_workflow_checkpointer,
    setup_workflow_checkpointer,
)
from app.workflow.exceptions import WorkflowStateError
from app.workflow.factory import create_workflow_service
from app.workflow.schemas import HumanDecision, ThreadId, WorkflowResumeCommand
from pydantic import TypeAdapter, ValidationError


def parse_args() -> argparse.Namespace:
    """Parse explicit setup, start, status, and resume commands."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "setup",
        help="Initialize the official PostgreSQL checkpoint tables after Alembic",
    )

    start = subparsers.add_parser("start", help="Start and pause a new workflow")
    start.add_argument("--project", required=True, help="Existing project slug")
    start.add_argument(
        "--query-type",
        choices=[item.value for item in QueryType],
        required=True,
    )
    start.add_argument("--brief", required=True)
    start.add_argument("--constraint", action="append", default=[])
    start.add_argument("--platform")
    start.add_argument("--method")
    start.add_argument("--positive-limit", type=int, default=5)
    start.add_argument("--failure-limit", type=int, default=5)
    start.add_argument("--minimum-similarity", type=float)
    start.add_argument("--trace-id")
    start.add_argument("--thread-id")
    start.add_argument("--provider", choices=("fake", "ollama"), default="fake")

    status = subparsers.add_parser("status", help="Inspect one durable workflow")
    status.add_argument("--thread-id", required=True)

    resume = subparsers.add_parser("resume", help="Resume one human review")
    resume.add_argument("--thread-id", required=True)
    resume.add_argument(
        "--decision",
        choices=[item.value for item in HumanDecision],
        required=True,
    )
    resume.add_argument("--feedback")

    reconcile = subparsers.add_parser(
        "reconcile",
        help="Safely release an unaccepted resume claim for one paused workflow",
    )
    reconcile.add_argument("--thread-id", required=True)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    """Execute one command with short-lived database and checkpointer resources."""
    settings = get_settings()
    database = Database(settings)
    try:
        async with open_workflow_checkpointer(settings) as checkpointer:
            if args.command == "setup":
                await setup_workflow_checkpointer(checkpointer, database)
                _print_json(
                    {
                        "status": "ready",
                        "schema": CHECKPOINT_SCHEMA,
                    }
                )
                return 0

            provider_kind = await _provider_kind(database, args)
            service = create_workflow_service(
                settings,
                database,
                checkpointer,
                provider_kind=provider_kind,
            )
            if args.command == "start":
                project_id = await _project_id(database, args.project)
                result = await service.start(
                    RecommendationRequest(
                        project_id=project_id,
                        brief=args.brief,
                        query_type=QueryType(args.query_type),
                        target_platform=args.platform,
                        generation_method=args.method,
                        constraints=list(args.constraint),
                        positive_limit=args.positive_limit,
                        failure_limit=args.failure_limit,
                        minimum_similarity=args.minimum_similarity,
                        trace_id=args.trace_id,
                    ),
                    thread_id=args.thread_id,
                )
            elif args.command == "status":
                result = await service.status(args.thread_id)
            elif args.command == "reconcile":
                result = await service.reconcile_unaccepted_resume(args.thread_id)
            else:
                result = await service.resume(
                    args.thread_id,
                    WorkflowResumeCommand(
                        decision=HumanDecision(args.decision),
                        feedback=args.feedback,
                    ),
                )
            _print_json(result.model_dump(mode="json"))
            return 0
    except ValidationError as exc:
        _print_error(
            "INPUT_VALIDATION_ERROR",
            "; ".join(error["msg"] for error in exc.errors()),
        )
        return 2
    except AlbaError as exc:
        _print_error(exc.detail.error_code, exc.detail.message)
        return 1
    except Exception:
        _print_error(
            "WORKFLOW_COMMAND_FAILED",
            "The workflow command failed without exposing internal details.",
        )
        return 1
    finally:
        await database.dispose()


async def _project_id(database: Database, slug: str) -> UUID:
    async with database.transaction() as session:
        project = await ProjectRepository(session).get_by_slug(slug)
        if project is None:
            raise EntityNotFoundError("Project", slug)
        return project.id


async def _provider_kind(
    database: Database,
    args: argparse.Namespace,
) -> RecommendationProviderKind:
    if args.command == "start":
        return cast(RecommendationProviderKind, args.provider)
    thread_id = cast(str, TypeAdapter(ThreadId).validate_python(args.thread_id))
    async with database.transaction() as session:
        run = await GenerationRunRepository(session).get_by_workflow_thread_id(thread_id)
        if run is None or run.provider == "fake":
            return "fake"
        if run.provider == "ollama":
            return "ollama"
        raise WorkflowStateError("The persisted workflow provider is not supported.")


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _print_error(error_code: str, message: str) -> None:
    print(
        json.dumps(
            {
                "error_code": error_code,
                "message": message,
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )


def main() -> None:
    settings = get_settings()
    if settings.workflow_diagnostics:
        logging.basicConfig(level=logging.INFO)
    coroutine = run(parse_args())
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            raise SystemExit(runner.run(coroutine))
    raise SystemExit(asyncio.run(coroutine))


if __name__ == "__main__":
    main()
