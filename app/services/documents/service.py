"""Document reads, signed previews, and (re)processing jobs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.signing import sign
from app.models import (
    Case,
    Document,
    DocumentPage,
    DocumentStage,
    DocumentStatus,
    DocumentVersion,
    ExtractedField,
    ExtractionRun,
    Job,
)
from app.schemas.common import Page, decode_cursor, encode_cursor
from app.schemas.documents import (
    DocumentOut,
    ExtractionOut,
    FieldOut,
    PageOut,
    PreviewOut,
    StageOut,
)
from app.services.audit import service as audit
from app.services.cases.service import get_case
from app.services.identity.principal import Principal, RequestMeta
from app.services.jobs import service as job_service

STAGE_ORDER = {"parse": 0, "classify": 1, "extract": 2, "validate": 3}
PROCESS_KIND = "document.process"


def page_image_name(page: int) -> str:
    return f"page-{page:04d}.png"


def _visible(org: uuid.UUID) -> Select[Any]:
    """Documents of this organization whose case isn't soft-deleted."""
    return (
        select(Document)
        .join(Case, Case.id == Document.case_id)
        .where(Document.organization_id == org, Case.deleted_at.is_(None))
    )


async def get_document(session: AsyncSession, org: uuid.UUID, document_id: uuid.UUID) -> Document:
    doc: Document | None = await session.scalar(_visible(org).where(Document.id == document_id))
    if doc is None:
        raise NotFoundError("Document not found.")
    return doc


async def _out(session: AsyncSession, docs: list[Document], with_stages: bool) -> list[DocumentOut]:
    ids = [d.id for d in docs]
    supersedes: dict[uuid.UUID, uuid.UUID] = {}
    stages: dict[uuid.UUID, list[StageOut]] = {}
    if ids:
        for v in await session.scalars(
            select(DocumentVersion).where(DocumentVersion.document_id.in_(ids))
        ):
            supersedes[v.document_id] = v.supersedes_id
        if with_stages:
            for row in await session.scalars(
                select(DocumentStage).where(DocumentStage.document_id.in_(ids))
            ):
                stages.setdefault(row.document_id, []).append(StageOut.model_validate(row))
    out = []
    for d in docs:
        item = DocumentOut.model_validate(d).model_copy(
            update={
                "supersedes_id": supersedes.get(d.id),
                "stages": sorted(stages.get(d.id, []), key=lambda s: STAGE_ORDER.get(s.stage, 9)),
            }
        )
        out.append(item)
    return out


async def list_for_case(
    session: AsyncSession, org: uuid.UUID, case_id: uuid.UUID
) -> list[DocumentOut]:
    await get_case(session, org, case_id)
    docs = list(
        await session.scalars(
            _visible(org)
            .where(Document.case_id == case_id)
            .order_by(Document.original_filename, Document.uploaded_at)
        )
    )
    return await _out(session, docs, with_stages=True)


async def list_all(
    session: AsyncSession,
    org: uuid.UUID,
    *,
    limit: int,
    cursor: str | None,
    status: str | None,
    doc_type: str | None,
    q: str | None,
) -> Page[DocumentOut]:
    stmt = _visible(org)
    if status:
        stmt = stmt.where(Document.status == status)
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    if q:
        pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(Document.original_filename.ilike(pattern, escape="\\"))
    if cursor:
        ts, did = decode_cursor(cursor, 2)
        try:
            before, after_id = datetime.fromisoformat(ts), uuid.UUID(did)
        except ValueError as exc:
            raise ValidationFailedError("Invalid pagination cursor.") from exc
        stmt = stmt.where(
            or_(
                Document.uploaded_at < before,
                (Document.uploaded_at == before) & (Document.id < after_id),
            )
        )
    docs = list(
        await session.scalars(
            stmt.order_by(Document.uploaded_at.desc(), Document.id.desc()).limit(limit + 1)
        )
    )
    items = await _out(session, docs[:limit], with_stages=False)
    nxt = None
    if len(docs) > limit and items:
        last = docs[limit - 1]
        nxt = encode_cursor(last.uploaded_at, last.id)
    return Page[DocumentOut](items=items, next_cursor=nxt)


async def get(session: AsyncSession, org: uuid.UUID, document_id: uuid.UUID) -> DocumentOut:
    [out] = await _out(session, [await get_document(session, org, document_id)], with_stages=True)
    return out


async def pages(session: AsyncSession, org: uuid.UUID, document_id: uuid.UUID) -> list[PageOut]:
    await get_document(session, org, document_id)
    rows = await session.scalars(
        select(DocumentPage)
        .where(DocumentPage.document_id == document_id, DocumentPage.organization_id == org)
        .order_by(DocumentPage.page_number)
    )
    return [PageOut.model_validate(r) for r in rows]


async def extractions(
    session: AsyncSession, org: uuid.UUID, document_id: uuid.UUID
) -> ExtractionOut | None:
    await get_document(session, org, document_id)
    run = await session.scalar(
        select(ExtractionRun)
        .where(ExtractionRun.document_id == document_id, ExtractionRun.organization_id == org)
        .order_by(ExtractionRun.started_at.desc())
        .limit(1)
    )
    if run is None:
        return None
    fields = await session.scalars(
        select(ExtractedField)
        .where(ExtractedField.extraction_run_id == run.id)
        .order_by(ExtractedField.name)
    )
    return ExtractionOut(
        run_id=run.id,
        document_id=document_id,
        method=run.method,
        provider=run.provider,
        model_version=run.model_version,
        prompt_version=run.prompt_version,
        pipeline_version=run.pipeline_version,
        notes=run.notes,
        finished_at=run.finished_at,
        fields=[FieldOut.model_validate(f) for f in fields],
    )


async def preview(
    session: AsyncSession,
    principal: Principal,
    document_id: uuid.UUID,
    meta: RequestMeta,
    page: int | None = None,
) -> PreviewOut:
    doc = await get_document(session, principal.organization_id, document_id)
    artifact, mime = "original", doc.mime_type
    if page is not None:
        if doc.mime_type != "image/tiff" or doc.page_count is None or page > doc.page_count:
            raise NotFoundError("No page image for this document and page.")
        artifact, mime = page_image_name(page), "image/png"
    token, expires = sign(
        doc.id, principal.organization_id, get_settings().signed_url_seconds, artifact=artifact
    )
    await audit.record(
        session,
        "document.access",
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        resource_type="document",
        resource_id=doc.id,
        meta=meta,
        metadata={"purpose": "preview", "artifact": artifact},
    )
    return PreviewOut(
        url=f"/api/v1/files/{token}",
        expires_at=datetime.fromtimestamp(expires, UTC),
        mime_type=mime,
    )


async def create_process_job(
    session: AsyncSession, principal: Principal, document_ids: list[uuid.UUID], reason: str
) -> Job:
    job = await job_service.create_job(
        session,
        principal.organization_id,
        PROCESS_KIND,
        created_by=principal.user_id,
        payload={"document_ids": [str(i) for i in document_ids], "reason": reason},
        max_attempts=2,
    )
    return job


async def process_case(
    session: AsyncSession, principal: Principal, case_id: uuid.UUID, meta: RequestMeta
) -> tuple[Job | None, list[uuid.UUID]]:
    """Queue every document of the case that isn't completed or already processing."""
    await get_case(session, principal.organization_id, case_id)
    ids = list(
        await session.scalars(
            select(Document.id).where(
                Document.organization_id == principal.organization_id,
                Document.case_id == case_id,
                Document.status.in_([DocumentStatus.UPLOADED, DocumentStatus.FAILED]),
            )
        )
    )
    job = await create_process_job(session, principal, ids, "case.process") if ids else None
    await audit.record(
        session,
        "case.process",
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        resource_type="case",
        resource_id=case_id,
        meta=meta,
        metadata={"documents": len(ids)},
    )
    return job, ids


async def retry(
    session: AsyncSession, principal: Principal, document_id: uuid.UUID, meta: RequestMeta
) -> Job:
    """Resume a failed document from its failed stage (succeeded stages are skipped)."""
    doc = await get_document(session, principal.organization_id, document_id)
    if doc.status != DocumentStatus.FAILED:
        raise ConflictError(f"Only failed documents can be retried (status is {doc.status}).")
    doc.status = DocumentStatus.UPLOADED
    job = await create_process_job(session, principal, [doc.id], "document.retry")
    await audit.record(
        session,
        "document.retry",
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        resource_type="document",
        resource_id=doc.id,
        meta=meta,
    )
    return job
