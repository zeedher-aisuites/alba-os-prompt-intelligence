"""Async engine, session lifecycle, and connectivity checks."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, cast

from fastapi import Depends, Request
from pydantic import PostgresDsn
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings
from app.domain.exceptions import DatabaseUnavailableError


class Database:
    """Application-scoped database resources without shared mutable sessions."""

    def __init__(
        self,
        settings: Settings,
        *,
        database_url: PostgresDsn | None = None,
    ) -> None:
        resolved_url = database_url or settings.database_url.get_secret_value()
        self.engine: AsyncEngine = create_async_engine(
            resolved_url.unicode_string(),
            echo=settings.database_echo,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout,
            pool_recycle=settings.database_pool_recycle,
            pool_pre_ping=True,
            connect_args={"server_settings": {"timezone": "UTC"}},
        )
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        """Yield one atomic unit of work with automatic commit or rollback."""
        async with self.session_factory() as session, session.begin():
            yield session

    async def check_connection(self) -> None:
        """Execute a minimal PostgreSQL readiness probe."""
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except (OSError, SQLAlchemyError) as exc:
            raise DatabaseUnavailableError from exc

    async def dispose(self) -> None:
        """Release pooled connections during application shutdown."""
        await self.engine.dispose()


def get_database(request: Request) -> Database:
    """Resolve the application-scoped database resource."""
    return cast(Database, request.app.state.database)


DatabaseDependency = Annotated[Database, Depends(get_database)]


async def get_session(database: DatabaseDependency) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency for one transactional session."""
    async with database.transaction() as session:
        yield session


SessionDependency = Annotated[AsyncSession, Depends(get_session)]
