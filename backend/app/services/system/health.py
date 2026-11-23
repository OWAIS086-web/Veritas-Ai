"""Dependency health checks."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.redis import get_redis
from app.integrations.graph.neo4j_store import get_store
from app.schemas.system import ComponentHealth, GraphSyncHealth, HealthResponse
from app.services.graph.sync import outbox_health

TIMEOUT_SECONDS = 2.0


async def _database() -> ComponentHealth:
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
        return ComponentHealth(status="ok")
    except Exception as exc:
        return ComponentHealth(status="error", detail=type(exc).__name__)


async def _redis() -> ComponentHealth:
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            await get_redis().ping()
        return ComponentHealth(status="ok")
    except Exception as exc:
        return ComponentHealth(status="error", detail=type(exc).__name__)


async def _graph() -> GraphSyncHealth:
    counts = {"pending": 0, "processing": 0, "dead": 0}
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            counts = await outbox_health()
    except Exception as exc:
        return GraphSyncHealth(status="error", detail=f"outbox: {type(exc).__name__}")
    pending = counts["pending"] + counts["processing"]
    if not get_settings().neo4j_password:
        return GraphSyncHealth(
            status="not_configured", outbox_pending=pending, outbox_dead=counts["dead"]
        )
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            await get_store().ping()
        status = "ok"
        detail = None
    except Exception as exc:
        status, detail = "error", type(exc).__name__
    return GraphSyncHealth(
        status=status,
        detail=detail,
        outbox_pending=pending,
        outbox_dead=counts["dead"],
    )


async def check() -> HealthResponse:
    database, redis, graph = await asyncio.gather(_database(), _redis(), _graph())
    components = {"database": database, "redis": redis}
    healthy = all(c.status == "ok" for c in components.values())
    return HealthResponse(
        status="ok" if healthy else "degraded", components=components, graph=graph
    )
