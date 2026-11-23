"""Apply graph outbox rows to Neo4j, and reconcile drift.

Rows are claimed across organizations through the owner-owned `outbox_claim` function (ids
only), then each row is processed inside its organization's tenant session. A failure puts
the row back as pending with exponential backoff; after `VERITAS_OUTBOX_MAX_ATTEMPTS` it is
marked dead and reported by the system health endpoint.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.db import session_scope, tenant_session
from app.core.logging import get_logger
from app.models import OutboxEvent
from app.services.graph.projection import CaseGraph
from app.services.graph.service import case_graph_from_postgres, enqueue_sync

logger = get_logger(__name__)


class GraphStore(Protocol):
    async def replace_case(self, org: uuid.UUID, case_id: uuid.UUID, graph: CaseGraph) -> None: ...
    async def counts(self, org: uuid.UUID, case_id: uuid.UUID) -> tuple[int, int]: ...
    async def case_keys(self) -> set[tuple[uuid.UUID, uuid.UUID]]: ...


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(600, 5 * 2 ** max(0, attempts - 1)))


async def _claim(limit: int) -> list[tuple[uuid.UUID, uuid.UUID]]:
    # The claim commits when the scope exits, so a crash after this point leaves the rows
    # in `processing`, and outbox_claim picks them up again after 10 minutes.
    async with session_scope() as s:
        rows = (
            await s.execute(text("SELECT id, organization_id FROM outbox_claim(:n)"), {"n": limit})
        ).all()
    return [(r[0], r[1]) for r in rows]


async def process_outbox(store: GraphStore, limit: int = 20) -> dict[str, int]:
    settings = get_settings()
    result = {"done": 0, "retry": 0, "dead": 0}
    for row_id, org in await _claim(limit):
        async with tenant_session(org) as s:
            row = await s.get(OutboxEvent, row_id)
            if row is None:
                continue
            case_id = uuid.UUID(str(row.payload["case_id"]))
            graph = await case_graph_from_postgres(s, org, case_id)
            try:
                await store.replace_case(org, case_id, graph)
            except Exception as exc:
                row.last_error = f"{type(exc).__name__}: {exc}"[:500]
                if row.attempts >= settings.outbox_max_attempts:
                    row.status = "dead"
                    result["dead"] += 1
                else:
                    row.status = "pending"
                    row.available_at = datetime.now(UTC) + backoff(row.attempts)
                    result["retry"] += 1
                logger.warning(
                    "graph_sync_failed",
                    extra={
                        "outbox": str(row_id),
                        "attempt": row.attempts,
                        "error": type(exc).__name__,
                    },
                )
                continue
            row.status = "done"
            row.processed_at = datetime.now(UTC)
            row.last_error = None
            result["done"] += 1
    return result


async def reconcile(store: GraphStore) -> dict[str, Any]:
    """Queue a rebuild for every case whose Neo4j counts differ from Postgres, and remove
    Neo4j subgraphs of cases that are deleted or no longer exist."""
    async with session_scope() as s:
        cases = {(r[0], r[1]) for r in (await s.execute(text("SELECT * FROM graph_cases()"))).all()}
    queued, removed = 0, 0
    for org, case_id in sorted(cases, key=str):
        async with tenant_session(org) as s:
            expected = await case_graph_from_postgres(s, org, case_id)
            pending = await s.scalar(
                select(OutboxEvent.id)
                .where(
                    OutboxEvent.organization_id == org,
                    OutboxEvent.status.in_(("pending", "processing")),
                    OutboxEvent.payload["case_id"].astext == str(case_id),
                )
                .limit(1)
            )
            if pending is not None:
                continue
            if await store.counts(org, case_id) != (len(expected.nodes), len(expected.edges)):
                await enqueue_sync(s, org, case_id)
                queued += 1
    for org, case_id in sorted(await store.case_keys() - cases, key=str):
        await store.replace_case(org, case_id, CaseGraph([], []))
        removed += 1
    return {"cases": len(cases), "queued": queued, "removed": removed}


async def outbox_health() -> dict[str, int]:
    async with session_scope() as s:
        rows = (await s.execute(text("SELECT status, n FROM outbox_health()"))).all()
    counts = {"pending": 0, "processing": 0, "dead": 0}
    counts.update({str(r[0]): int(r[1]) for r in rows})
    return counts
