"""Forensic results for the API. Every query filters organization_id (RLS is the backstop);
documents of deleted cases and other organizations are a 404."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models import Case, Document, ForensicAnomaly, ForensicRun
from app.schemas.forensics import ForensicAnomalyOut, ForensicRunOut, ForensicSummaryOut
from app.services.cases.service import get_case

SEVERITY_ORDER = {"medium": 0, "low": 1, "info": 2}


async def _document(s: AsyncSession, org: uuid.UUID, document_id: uuid.UUID) -> Document:
    doc = await s.scalar(
        select(Document)
        .join(Case, Case.id == Document.case_id)
        .where(
            Document.id == document_id,
            Document.organization_id == org,
            Case.deleted_at.is_(None),
        )
    )
    if doc is None:
        raise NotFoundError("Document not found.")
    return doc


async def latest_run(
    s: AsyncSession, org: uuid.UUID, document_id: uuid.UUID
) -> ForensicRunOut | None:
    await _document(s, org, document_id)
    run = await s.scalar(
        select(ForensicRun)
        .where(ForensicRun.organization_id == org, ForensicRun.document_id == document_id)
        .order_by(ForensicRun.started_at.desc())
        .limit(1)
    )
    if run is None:
        return None
    anomalies = list(
        await s.scalars(
            select(ForensicAnomaly).where(
                ForensicAnomaly.organization_id == org, ForensicAnomaly.forensic_run_id == run.id
            )
        )
    )
    anomalies.sort(key=lambda a: (SEVERITY_ORDER.get(a.severity, 9), a.page_number or 0, a.type))
    out = ForensicRunOut.model_validate(run)
    return out.model_copy(
        update={"anomalies": [ForensicAnomalyOut.model_validate(a) for a in anomalies]}
    )


async def case_summary(
    s: AsyncSession, org: uuid.UUID, case_id: uuid.UUID
) -> list[ForensicSummaryOut]:
    await get_case(s, org, case_id)
    docs = list(
        await s.scalars(
            select(Document)
            .where(
                Document.organization_id == org,
                Document.case_id == case_id,
            )
            .order_by(Document.uploaded_at, Document.id)
        )
    )
    latest: dict[uuid.UUID, ForensicRun] = {}
    if docs:
        for run in await s.scalars(
            select(ForensicRun)
            .where(
                ForensicRun.organization_id == org,
                ForensicRun.document_id.in_([d.id for d in docs]),
            )
            .order_by(ForensicRun.started_at.desc())
        ):
            latest.setdefault(run.document_id, run)
    counts: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    types: dict[uuid.UUID, set[str]] = defaultdict(set)
    if latest:
        for a in await s.scalars(
            select(ForensicAnomaly).where(
                ForensicAnomaly.organization_id == org,
                ForensicAnomaly.forensic_run_id.in_([r.id for r in latest.values()]),
            )
        ):
            counts[a.document_id][a.severity] += 1
            types[a.document_id].add(a.type)
    out = []
    for d in docs:
        doc_run = latest.get(d.id)
        c = counts[d.id]
        out.append(
            ForensicSummaryOut(
                document_id=d.id,
                filename=d.original_filename,
                doc_type=d.doc_type,
                mime_type=d.mime_type,
                status=doc_run.status if doc_run else None,
                analysis_types=doc_run.analysis_types if doc_run else [],
                anomalies=sum(c.values()),
                medium=c["medium"],
                low=c["low"],
                types=sorted(types[d.id]),
            )
        )
    out.sort(key=lambda x: (-x.medium, -x.anomalies, x.filename))
    return out
