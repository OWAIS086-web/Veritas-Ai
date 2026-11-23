"""Async SQLAlchemy engine, sessions and tenant context.

The app connects as the non-owner role (veritas_app), so Postgres row-level security
applies to every query. Tenant context is set per transaction with set_config(..., true),
which behaves like SET LOCAL and accepts a bound parameter.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    if settings.db_null_pool:
        return create_async_engine(settings.database_url, poolclass=NullPool)
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        pool_pre_ping=True,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def set_tenant(session: AsyncSession, organization_id: uuid.UUID) -> None:
    """Bind the transaction to one organization for row-level security."""
    await session.execute(
        text("SELECT set_config('app.current_org', :org, true)"),
        {"org": str(organization_id)},
    )


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """A session with one transaction: commit on success, roll back on error."""
    async with get_sessionmaker()() as session, session.begin():
        yield session


@asynccontextmanager
async def tenant_session(organization_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        await set_tenant(session, organization_id)
        yield session


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one transaction per request, without tenant context."""
    async with session_scope() as session:
        yield session
