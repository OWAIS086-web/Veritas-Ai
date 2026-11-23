"""Celery tasks that keep Neo4j in step with Postgres (scheduled by the embedded beat)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.integrations.graph.neo4j_store import GraphUnavailableError, Neo4jStore, make_store
from app.services.graph.sync import process_outbox, reconcile
from app.workers.celery_app import celery_app


async def _with_store(fn: Callable[[Neo4jStore], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    # A fresh driver per run: each task runs in its own event loop (asyncio.run).
    store = make_store()
    try:
        await store.ensure_schema()
        return await fn(store)
    finally:
        await store.close()


@celery_app.task(name="graph.drain_outbox", time_limit=300, soft_time_limit=270)
def drain_outbox() -> dict[str, Any]:
    async def run(store: Neo4jStore) -> dict[str, Any]:
        return await process_outbox(store)

    try:
        return asyncio.run(_with_store(run))
    except GraphUnavailableError as exc:
        # Rows stay pending; the next scheduled run retries them.
        return {"unavailable": str(exc)}


@celery_app.task(name="graph.reconcile", time_limit=600, soft_time_limit=570)
def reconcile_graph() -> dict[str, Any]:
    try:
        return asyncio.run(_with_store(reconcile))
    except GraphUnavailableError as exc:
        return {"unavailable": str(exc)}
