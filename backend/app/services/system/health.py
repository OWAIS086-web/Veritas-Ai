"""Dependency health checks."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.redis import get_redis
from app.integrations.graph.neo4j_store import get_store
from app.integrations.storage.s3_store import get_store as get_object_store
from app.schemas.system import ComponentHealth, GraphSyncHealth, HealthResponse
from app.services.graph.sync import outbox_health

TIMEOUT_SECONDS = 2.0
WORKER_PING_SECONDS = 1.0


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


async def _storage() -> ComponentHealth:
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            await get_object_store().ping()
        return ComponentHealth(status="ok")
    except Exception as exc:
        return ComponentHealth(status="error", detail=type(exc).__name__)


def _ping_workers() -> int:
    # Imported here so the API loads the Celery app (not the task modules) only for this check.
    from app.workers.celery_app import celery_app

    return len(celery_app.control.ping(timeout=WORKER_PING_SECONDS) or [])


async def _worker() -> ComponentHealth:
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            replies = await asyncio.to_thread(_ping_workers)
    except Exception as exc:
        return ComponentHealth(status="error", detail=type(exc).__name__)
    if replies == 0:
        return ComponentHealth(status="error", detail="no worker answered the ping")
    # The count only: worker host names aren't shown on this unauthenticated endpoint.
    return ComponentHealth(status="ok", detail=f"{replies} worker(s) answered")


async def check() -> HealthResponse:
    database, redis, graph, storage, worker = await asyncio.gather(
        _database(), _redis(), _graph(), _storage(), _worker()
    )
    components = {"database": database, "redis": redis}
    healthy = all(c.status == "ok" for c in components.values())
    return HealthResponse(
        status="ok" if healthy else "degraded",
        components=components,
        graph=graph,
        services={"storage": storage, "worker": worker},
    )
