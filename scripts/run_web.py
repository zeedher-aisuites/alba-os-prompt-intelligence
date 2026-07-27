"""Start the local Alba OS web application with a Windows-safe event loop."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence

import uvicorn

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
LOCAL_HOSTS = ("127.0.0.1", "::1")
SELECTOR_LOOP_FACTORY = "scripts.run_web:selector_loop_factory"


def parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the intentionally local-only server options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=LOCAL_HOSTS, default=DEFAULT_HOST)
    parser.add_argument("--port", type=_port, default=_default_port())
    return parser.parse_args(arguments)


def configure_event_loop_policy() -> bool:
    """Install Selector policy before Uvicorn owns the event loop on Windows."""
    if sys.platform != "win32":
        return False
    policy_type = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy_type is None:
        raise RuntimeError("Windows Selector event loop policy is unavailable.")
    asyncio.set_event_loop_policy(policy_type())
    return True


def selector_loop_factory(*, use_subprocess: bool = False) -> asyncio.AbstractEventLoop:
    """Force the Psycopg-compatible loop Uvicorn 0.36 otherwise bypasses on Windows."""
    del use_subprocess
    return asyncio.SelectorEventLoop()


def run_server(arguments: Sequence[str] | None = None) -> None:
    """Launch Uvicorn without reload and without a publicly reachable default bind."""
    args = parse_args(arguments)
    configure_event_loop_policy()
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        loop=SELECTOR_LOOP_FACTORY,
        reload=False,
    )


def _default_port() -> int:
    return _port(os.environ.get("ALBA_WEB_PORT", str(DEFAULT_PORT)))


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65_535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


if __name__ == "__main__":
    run_server()
