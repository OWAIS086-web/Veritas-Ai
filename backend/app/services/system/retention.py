"""Retention purge: remove the cases whose organization's retention period has passed.

A case expires when its last change (its soft deletion, if it was deleted) is older than
`organizations.retention_days`; organizations without a value keep their data. For each
expired case the purge deletes the storage objects of its documents, reports and comparisons
(originals included: this is the only path that deletes them), then the case row through the
`purge_expired_case` database function, which cascades to every row under it and re-checks the
expiry. The graph reconciler then removes the case's Neo4j subgraph. One audit entry per
organization records counts only.

Storage goes first: if the row delete then fails, the next run deletes the same, already
emptied prefixes again. The reverse order could leave objects that nothing references.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text

from app.core.db import session_scope, tenant_session
from app.core.logging import get_logger
from app.integrations.storage.base import ObjectStore, resource_prefix
from app.models import Case, Document, DocumentComparison, Report
from app.services.audit import service as audit

logger = get_logger(__name__)


async def _expired(org: uuid.UUID, days: int) -> list[uuid.UUID]:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    async with tenant_session(org) as s:
        return list(
            await s.scalars(
                select(Case.id).where(
                    Case.organization_id == org,
                    func.coalesce(Case.deleted_at, Case.updated_at) < cutoff,
                )
            )
        )


async def _resources(org: uuid.UUID, case_id: uuid.UUID) -> tuple[list[uuid.UUID], int]:
    """Storage owners of one case (documents, reports, comparisons) and its document count."""
    async with tenant_session(org) as s:
        docs = list(
            await s.scalars(
                select(Document.id).where(
                    Document.organization_id == org, Document.case_id == case_id
                )
            )
        )
        reports = list(
            await s.scalars(
                select(Report.id).where(Report.organization_id == org, Report.case_id == case_id)
            )
        )
        comparisons = list(
            await s.scalars(
                select(DocumentComparison.id).where(
                    DocumentComparison.organization_id == org, DocumentComparison.case_id == case_id
                )
            )
        )
    return [*docs, *reports, *comparisons], len(docs)


async def purge_organization(org: uuid.UUID, days: int, store: ObjectStore) -> dict[str, int]:
    counts = {"cases": 0, "documents": 0, "objects": 0, "failed": 0}
    for case_id in await _expired(org, days):
        owners, documents = await _resources(org, case_id)
        try:
            for owner in owners:
                counts["objects"] += await store.delete_prefix(resource_prefix(org, owner))
            async with tenant_session(org) as s:
                deleted = await s.scalar(
                    text("SELECT purge_expired_case(:case_id)"), {"case_id": case_id}
                )
        except Exception as exc:
            counts["failed"] += 1
            logger.warning("retention_purge_failed", extra={"error": type(exc).__name__})
            continue
        if deleted:
            counts["cases"] += 1
            counts["documents"] += documents
    if any(counts.values()):
        async with tenant_session(org) as s:
            await audit.record(
                s,
                "retention.purge",
                organization_id=org,
                resource_type="organization",
                resource_id=org,
                metadata={**counts, "retention_days": days},
            )
    return counts


async def purge_expired(store: ObjectStore) -> dict[str, Any]:
    """Every organization with a retention period (worker task `system.retention_purge`)."""
    async with session_scope() as s:
        orgs = (await s.execute(text("SELECT * FROM retention_organizations()"))).all()
    totals = {"organizations": len(orgs), "cases": 0, "documents": 0, "objects": 0, "failed": 0}
    for org, days in orgs:
        result = await purge_organization(org, int(days), store)
        for key in ("cases", "documents", "objects", "failed"):
            totals[key] += result[key]
    logger.info("retention_purge", extra=totals)
    return totals
