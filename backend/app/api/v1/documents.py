"""Document reads, retry, signed preview and the signed file endpoint."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, request_meta, require_permission
from app.core.db import tenant_session
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.signing import InvalidSignatureError, verify
from app.integrations.storage.base import ObjectNotFoundError, derived_key
from app.integrations.storage.s3_store import get_store
from app.models import Case, Document
from app.schemas.common import PROBLEM_RESPONSES, Page
from app.schemas.documents import DocumentOut, ExtractionOut, PageOut, PreviewOut
from app.schemas.system import JobOut
from app.services.audit import service as audit
from app.services.documents import service as document_service
from app.services.identity.principal import Principal, RequestMeta
from app.workers.dispatch import enqueue_processing

router = APIRouter(tags=["documents"], responses=PROBLEM_RESPONSES)
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]")


@router.get(
    "/documents",
    response_model=Page[DocumentOut],
    summary="All documents of the organization (filters: status, type, filename)",
)
async def list_documents(
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None, max_length=100),
    status_filter: str | None = Query(
        None, alias="status", pattern="^(uploaded|processing|completed|failed)$"
    ),
    doc_type: str | None = Query(None, max_length=60),
    q: str | None = Query(None, max_length=100),
    principal: Principal = Depends(require_permission("documents:read")),
    session: AsyncSession = Depends(db_session),
) -> Page[DocumentOut]:
    return await document_service.list_all(
        session,
        principal.organization_id,
        limit=limit,
        cursor=cursor,
        status=status_filter,
        doc_type=doc_type,
        q=q,
    )


@router.get(
    "/documents/{document_id}", response_model=DocumentOut, summary="Document metadata and stages"
)
async def get_document(
    document_id: uuid.UUID,
    principal: Principal = Depends(require_permission("documents:read")),
    session: AsyncSession = Depends(db_session),
) -> DocumentOut:
    return await document_service.get(session, principal.organization_id, document_id)


@router.get(
    "/documents/{document_id}/pages",
    response_model=list[PageOut],
    summary="Page text, lines with boxes or locations, and tables",
)
async def get_pages(
    document_id: uuid.UUID,
    principal: Principal = Depends(require_permission("documents:read")),
    session: AsyncSession = Depends(db_session),
) -> list[PageOut]:
    return await document_service.pages(session, principal.organization_id, document_id)


@router.get(
    "/documents/{document_id}/extractions",
    response_model=ExtractionOut | None,
    summary="Latest extraction run and its fields with provenance",
)
async def get_extractions(
    document_id: uuid.UUID,
    principal: Principal = Depends(require_permission("documents:read")),
    session: AsyncSession = Depends(db_session),
) -> ExtractionOut | None:
    return await document_service.extractions(session, principal.organization_id, document_id)


@router.get(
    "/documents/{document_id}/preview",
    response_model=PreviewOut,
    summary="Short-lived signed URL for the original file (audited)",
)
async def get_preview(
    document_id: uuid.UUID,
    page: int | None = Query(None, ge=1, le=5000, description="Page image (TIFF only)"),
    principal: Principal = Depends(require_permission("documents:read")),
    session: AsyncSession = Depends(db_session),
    meta: RequestMeta = Depends(request_meta),
) -> PreviewOut:
    return await document_service.preview(session, principal, document_id, meta, page)


@router.post(
    "/documents/{document_id}/retry",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Resume a failed document from its failed stage",
)
async def retry_document(
    document_id: uuid.UUID,
    background: BackgroundTasks,
    principal: Principal = Depends(require_permission("documents:process")),
    session: AsyncSession = Depends(db_session),
    meta: RequestMeta = Depends(request_meta),
) -> JobOut:
    job = await document_service.retry(session, principal, document_id, meta)
    background.add_task(enqueue_processing, principal.organization_id, job.id)
    return JobOut.model_validate(job)


@router.get(
    "/files/{token}",
    responses={
        200: {"content": {"application/octet-stream": {}}},
        403: {"description": "Invalid or expired link"},
    },
    summary="Serve an original through a signed link (no bearer token; the link expires)",
)
async def get_file(
    token: str = Path(max_length=400),
    meta: RequestMeta = Depends(request_meta),
) -> Response:
    try:
        grant = verify(token)
    except InvalidSignatureError as exc:
        raise PermissionDeniedError("This file link is invalid or has expired.") from exc
    async with tenant_session(grant.organization_id) as session:
        doc = await session.scalar(
            select(Document)
            .join(Case, Case.id == Document.case_id)
            .where(
                Document.id == grant.document_id,
                Document.organization_id == grant.organization_id,
                Case.deleted_at.is_(None),
            )
        )
        if doc is None:
            raise NotFoundError("Document not found.")
        await audit.record(
            session,
            "document.download",
            organization_id=grant.organization_id,
            resource_type="document",
            resource_id=doc.id,
            meta=meta,
            metadata={"via": "signed_link"},
        )
        if grant.artifact == "original":
            key, mime, name = doc.storage_key, doc.mime_type, doc.original_filename
        else:  # a derived page image; the original is untouched
            key = derived_key(grant.organization_id, doc.id, grant.artifact)
            mime, name = "image/png", grant.artifact
    try:
        data = await get_store().get(key)
    except ObjectNotFoundError as exc:
        raise NotFoundError("File not found.") from exc
    safe = _SAFE_NAME.sub("_", name)[:150] or "document"
    return Response(
        content=data,
        media_type=mime,
        headers={
            "Content-Disposition": f'inline; filename="{safe}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            # The original is untrusted content: if opened directly it gets no script privileges.
            "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'",
        },
    )
