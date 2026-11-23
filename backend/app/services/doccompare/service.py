"""Comparisons on the API side: create (from case documents or a fresh upload pair), list,
read, retry, human review, exports and signed download links.

Every query filters `organization_id` (RLS is the backstop); another organization's comparison,
finding or export is a 404. The analysis itself runs in the worker (`doccompare.run`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.signing import COMPARISON_EXPORT_ARTIFACT, sign
from app.integrations.storage.base import ObjectStore
from app.models import (
    COMPARISON_LIMITATION,
    Case,
    ComparisonExport,
    ComparisonFinding,
    ComparisonReview,
    Document,
    DocumentComparison,
    User,
)
from app.schemas.doccompare import (
    ComparisonDetail,
    ComparisonExportOut,
    ComparisonFindingOut,
    ComparisonOut,
    ComparisonUploadOut,
    ReviewEntryOut,
    ReviewIn,
)
from app.schemas.reporting import DownloadOut
from app.services.audit import service as audit
from app.services.cases.service import get_case
from app.services.doccompare.pages import IMAGE_TYPES, PDF
from app.services.documents import service as documents
from app.services.identity.principal import Principal, RequestMeta
from app.services.ingestion import service as ingestion

COMPARABLE = {PDF, *IMAGE_TYPES}
EXPORT_MIME = {
    "annotated_pdf": ("application/pdf", "pdf"),
    "annotated_images": ("application/zip", "zip"),
    "report_pdf": ("application/pdf", "pdf"),
    "findings_json": ("application/json", "json"),
}


def settings_snapshot() -> dict[str, Any]:
    s = get_settings()
    return {
        "dpi": s.comparison_dpi,
        "max_pages": s.comparison_max_pages,
        "work_width": s.comparison_work_width,
        "ssim_threshold": s.comparison_ssim_threshold,
        "vlm_enabled": s.comparison_vlm_enabled,
        "vlm_model": s.vlm_model or None,
        "vlm_max_regions": s.comparison_vlm_max_regions,
        "vlm_max_pages": s.comparison_vlm_max_pages,
    }


def _visible(org: uuid.UUID) -> Select[Any]:
    return (
        select(DocumentComparison)
        .join(Case, Case.id == DocumentComparison.case_id)
        .where(DocumentComparison.organization_id == org, Case.deleted_at.is_(None))
    )


async def get_comparison(
    s: AsyncSession, org: uuid.UUID, comparison_id: uuid.UUID, lock: bool = False
) -> DocumentComparison:
    stmt = _visible(org).where(DocumentComparison.id == comparison_id)
    if lock:
        stmt = stmt.with_for_update(of=DocumentComparison)
    c = (await s.scalars(stmt)).first()
    if not isinstance(c, DocumentComparison):
        raise NotFoundError("Comparison not found.")
    return c


async def _outs(s: AsyncSession, rows: list[DocumentComparison]) -> list[ComparisonOut]:
    if not rows:
        return []
    doc_ids = {r.original_document_id for r in rows} | {r.test_document_id for r in rows}
    names: dict[uuid.UUID, str] = {
        doc_id: name
        for doc_id, name in await s.execute(
            select(Document.id, Document.original_filename).where(Document.id.in_(doc_ids))
        )
    }
    counts: dict[uuid.UUID, tuple[int, int]] = {}
    for cid, total, open_ in await s.execute(
        select(
            ComparisonFinding.comparison_id,
            func.count(),
            func.count().filter(ComparisonFinding.review_status == "unreviewed"),
        )
        .where(ComparisonFinding.comparison_id.in_([r.id for r in rows]))
        .group_by(ComparisonFinding.comparison_id)
    ):
        counts[cid] = (int(total), int(open_))
    return [
        ComparisonOut.model_validate(r).model_copy(
            update={
                "original_filename": names.get(r.original_document_id),
                "test_filename": names.get(r.test_document_id),
                "findings_count": counts.get(r.id, (0, 0))[0],
                "findings_unreviewed": counts.get(r.id, (0, 0))[1],
            }
        )
        for r in rows
    ]


async def _check_documents(
    s: AsyncSession, org: uuid.UUID, case_id: uuid.UUID, original_id: uuid.UUID, test_id: uuid.UUID
) -> tuple[Document, Document]:
    if original_id == test_id:
        raise ValidationFailedError("The original and the test document must be different.")
    pair = []
    for doc_id in (original_id, test_id):
        doc = await documents.get_document(s, org, doc_id)
        if doc.case_id != case_id:
            raise NotFoundError("Document not found in this case.")
        if doc.mime_type not in COMPARABLE:
            raise ValidationFailedError(
                f"{doc.original_filename} is {doc.mime_type}; only PDF and PNG, JPEG or TIFF "
                "images can be compared visually."
            )
        pair.append(doc)
    return pair[0], pair[1]


async def create(
    s: AsyncSession,
    principal: Principal,
    case_id: uuid.UUID,
    original_id: uuid.UUID,
    test_id: uuid.UUID,
    meta: RequestMeta,
) -> ComparisonOut:
    org = principal.organization_id
    await get_case(s, org, case_id)
    await _check_documents(s, org, case_id, original_id, test_id)
    c = DocumentComparison(
        id=uuid.uuid4(),
        organization_id=org,
        case_id=case_id,
        original_document_id=original_id,
        test_document_id=test_id,
        status="queued",
        progress=0,
        settings=settings_snapshot(),
        summary={},
        vlm_status="not_run",
        created_by=principal.user_id,
    )
    s.add(c)
    await s.flush()
    await audit.record(
        s,
        "comparison.create",
        organization_id=org,
        actor_user_id=principal.user_id,
        resource_type="document_comparison",
        resource_id=c.id,
        meta=meta,
        metadata={
            "case_id": str(case_id),
            "original_document_id": str(original_id),
            "test_document_id": str(test_id),
        },
    )
    await s.refresh(c)
    [out] = await _outs(s, [c])
    return out


async def upload_and_create(
    s: AsyncSession,
    store: ObjectStore,
    principal: Principal,
    case_id: uuid.UUID,
    original: ingestion.IncomingFile,
    test: ingestion.IncomingFile,
    meta: RequestMeta,
) -> tuple[ComparisonUploadOut, list[uuid.UUID]]:
    """Upload both files through the normal ingestion (type check, hash, immutable storage),
    then create the comparison. Returns the response and the newly accepted document ids,
    which the caller queues for processing."""
    org = principal.organization_id
    await get_case(s, org, case_id)
    results = []
    ids: list[uuid.UUID] = []
    for role, incoming in (("original", original), ("test", test)):
        [result] = await ingestion.upload(s, store, principal, case_id, [incoming], meta)
        if result.status == "rejected" or result.document_id is None:
            raise ValidationFailedError(
                f"The {role} file was rejected ({result.reason or 'unsupported'})."
            )
        results.append(result)
        ids.append(result.document_id)
    if ids[0] == ids[1]:
        raise ConflictError(
            "The original and the test file are byte-for-byte identical (same SHA-256); there "
            "is nothing to compare."
        )
    accepted = [r.document_id for r in results if r.status == "accepted" and r.document_id]
    out = await create(s, principal, case_id, ids[0], ids[1], meta)
    upload = ComparisonUploadOut(comparison=out, original=results[0], test=results[1])
    return upload, accepted


async def list_for_case(s: AsyncSession, org: uuid.UUID, case_id: uuid.UUID) -> list[ComparisonOut]:
    await get_case(s, org, case_id)
    rows = list(
        await s.scalars(
            _visible(org)
            .where(DocumentComparison.case_id == case_id)
            .order_by(DocumentComparison.created_at.desc())
            .limit(100)
        )
    )
    return await _outs(s, rows)


async def findings(
    s: AsyncSession, org: uuid.UUID, comparison_id: uuid.UUID
) -> list[ComparisonFinding]:
    return list(
        await s.scalars(
            select(ComparisonFinding)
            .where(
                ComparisonFinding.organization_id == org,
                ComparisonFinding.comparison_id == comparison_id,
            )
            .order_by(ComparisonFinding.number)
        )
    )


async def exports(
    s: AsyncSession, org: uuid.UUID, comparison_id: uuid.UUID
) -> list[ComparisonExport]:
    return list(
        await s.scalars(
            select(ComparisonExport)
            .where(
                ComparisonExport.organization_id == org,
                ComparisonExport.comparison_id == comparison_id,
            )
            .order_by(ComparisonExport.created_at.desc())
        )
    )


async def detail(s: AsyncSession, org: uuid.UUID, comparison_id: uuid.UUID) -> ComparisonDetail:
    c = await get_comparison(s, org, comparison_id)
    [out] = await _outs(s, [c])
    return ComparisonDetail(
        **out.model_dump(),
        settings=c.settings or {},
        summary=c.summary or {},
        limitation=COMPARISON_LIMITATION,
        findings=[ComparisonFindingOut.model_validate(f) for f in await findings(s, org, c.id)],
        exports=[ComparisonExportOut.model_validate(e) for e in await exports(s, org, c.id)],
    )


async def retry(
    s: AsyncSession, principal: Principal, comparison_id: uuid.UUID, meta: RequestMeta
) -> ComparisonOut:
    c = await get_comparison(s, principal.organization_id, comparison_id, lock=True)
    if c.status != "failed":
        raise ConflictError(f"Only a failed comparison can be retried (status is {c.status}).")
    c.status, c.stage, c.progress, c.error = "queued", None, 0, None
    c.settings = settings_snapshot()
    c.started_at = c.finished_at = None
    await audit.record(
        s,
        "comparison.retry",
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        resource_type="document_comparison",
        resource_id=c.id,
        meta=meta,
    )
    [out] = await _outs(s, [c])
    return out


async def _finding(
    s: AsyncSession, org: uuid.UUID, comparison_id: uuid.UUID, finding_id: uuid.UUID, lock: bool
) -> ComparisonFinding:
    await get_comparison(s, org, comparison_id)
    stmt = select(ComparisonFinding).where(
        ComparisonFinding.id == finding_id,
        ComparisonFinding.organization_id == org,
        ComparisonFinding.comparison_id == comparison_id,
    )
    f = await s.scalar(stmt.with_for_update() if lock else stmt)
    if f is None:
        raise NotFoundError("Finding not found.")
    return f


async def review(
    s: AsyncSession,
    principal: Principal,
    comparison_id: uuid.UUID,
    finding_id: uuid.UUID,
    body: ReviewIn,
    meta: RequestMeta,
) -> ComparisonFindingOut:
    org = principal.organization_id
    f = await _finding(s, org, comparison_id, finding_id, lock=True)
    before = f.review_status
    note = (body.note or "").strip() or None
    f.review_status = body.status
    f.reviewed_by = principal.user_id
    f.reviewed_at = datetime.now(UTC)
    s.add(
        ComparisonReview(
            organization_id=org,
            finding_id=f.id,
            actor_user_id=principal.user_id,
            from_status=before,
            to_status=body.status,
            note=note,
        )
    )
    await audit.record(
        s,
        "comparison.review",
        organization_id=org,
        actor_user_id=principal.user_id,
        resource_type="comparison_finding",
        resource_id=f.id,
        meta=meta,
        metadata={"comparison_id": str(comparison_id), "from": before, "to": body.status},
    )
    await s.flush()
    await s.refresh(f)
    return ComparisonFindingOut.model_validate(f)


async def review_history(
    s: AsyncSession, org: uuid.UUID, comparison_id: uuid.UUID, finding_id: uuid.UUID
) -> list[ReviewEntryOut]:
    await _finding(s, org, comparison_id, finding_id, lock=False)
    rows = await s.execute(
        select(ComparisonReview, User.email)
        .outerjoin(User, User.id == ComparisonReview.actor_user_id)
        .where(ComparisonReview.organization_id == org, ComparisonReview.finding_id == finding_id)
        .order_by(ComparisonReview.created_at)
    )
    return [
        ReviewEntryOut.model_validate(r).model_copy(update={"actor_email": email})
        for r, email in rows
    ]


async def request_export(
    s: AsyncSession, principal: Principal, comparison_id: uuid.UUID, kind: str, meta: RequestMeta
) -> ComparisonExportOut:
    org = principal.organization_id
    c = await get_comparison(s, org, comparison_id)
    if c.status != "completed":
        raise ConflictError(f"The comparison is {c.status}; exports need a completed comparison.")
    e = ComparisonExport(
        id=uuid.uuid4(),
        organization_id=org,
        comparison_id=c.id,
        kind=kind,
        status="queued",
        created_by=principal.user_id,
    )
    s.add(e)
    await s.flush()
    await audit.record(
        s,
        "comparison.export_request",
        organization_id=org,
        actor_user_id=principal.user_id,
        resource_type="comparison_export",
        resource_id=e.id,
        meta=meta,
        metadata={"comparison_id": str(c.id), "kind": kind},
    )
    await s.refresh(e)
    return ComparisonExportOut.model_validate(e)


async def list_exports(
    s: AsyncSession, org: uuid.UUID, comparison_id: uuid.UUID
) -> list[ComparisonExportOut]:
    await get_comparison(s, org, comparison_id)
    return [ComparisonExportOut.model_validate(e) for e in await exports(s, org, comparison_id)]


async def get_export(s: AsyncSession, org: uuid.UUID, export_id: uuid.UUID) -> ComparisonExport:
    e = await s.scalar(
        select(ComparisonExport)
        .join(DocumentComparison, DocumentComparison.id == ComparisonExport.comparison_id)
        .join(Case, Case.id == DocumentComparison.case_id)
        .where(
            ComparisonExport.id == export_id,
            ComparisonExport.organization_id == org,
            Case.deleted_at.is_(None),
        )
    )
    if e is None:
        raise NotFoundError("Export not found.")
    return e


async def download_link(
    s: AsyncSession, principal: Principal, export_id: uuid.UUID, meta: RequestMeta
) -> DownloadOut:
    org = principal.organization_id
    e = await get_export(s, org, export_id)
    if e.status != "completed":
        raise ConflictError(f"The export is {e.status}; there is no file to download.")
    token, expires = sign(
        e.id, org, get_settings().signed_url_seconds, artifact=COMPARISON_EXPORT_ARTIFACT
    )
    await audit.record(
        s,
        "comparison.export_access",
        organization_id=org,
        actor_user_id=principal.user_id,
        resource_type="comparison_export",
        resource_id=e.id,
        meta=meta,
        metadata={"purpose": "download_link", "kind": e.kind},
    )
    return DownloadOut(
        url=f"/api/v1/comparison-files/{token}", expires_at=datetime.fromtimestamp(expires, UTC)
    )


def export_file_name(e: ComparisonExport) -> str:
    _, ext = EXPORT_MIME[e.kind]
    return f"veritas-comparison-{str(e.comparison_id)[:8]}-{e.kind.replace('_', '-')}.{ext}"
