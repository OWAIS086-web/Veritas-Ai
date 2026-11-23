"""Cases, document upload into a case, and case processing."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, request_meta, require_permission
from app.core.config import get_settings
from app.integrations.storage.s3_store import get_store
from app.schemas.common import PROBLEM_RESPONSES, Page
from app.schemas.documents import (
    CaseCreate,
    CaseOut,
    CaseUpdate,
    DocumentOut,
    ProcessResponse,
    UploadResponse,
)
from app.services.cases import service as case_service
from app.services.documents import service as document_service
from app.services.identity.principal import Principal, RequestMeta
from app.services.ingestion import service as ingestion
from app.workers.dispatch import enqueue_processing

router = APIRouter(prefix="/cases", tags=["cases"], responses=PROBLEM_RESPONSES)
READ_CHUNK = 1024 * 1024


@router.get("", response_model=Page[CaseOut], summary="Cases of the organization")
async def list_cases(
    limit: int = Query(25, ge=1, le=100),
    cursor: str | None = Query(None, max_length=100),
    status_filter: str | None = Query(None, alias="status", pattern="^(open|closed)$"),
    priority: str | None = Query(None, pattern="^(low|medium|high|critical)$"),
    q: str | None = Query(None, max_length=100),
    principal: Principal = Depends(require_permission("cases:read")),
    session: AsyncSession = Depends(db_session, scope="function"),
) -> Page[CaseOut]:
    return await case_service.list_cases(
        session,
        principal.organization_id,
        limit=limit,
        cursor=cursor,
        status=status_filter,
        priority=priority,
        q=q,
    )


@router.post(
    "",
    response_model=CaseOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an investigation case",
)
async def create_case(
    body: CaseCreate,
    principal: Principal = Depends(require_permission("cases:write")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> CaseOut:
    return await case_service.create(session, principal, body, meta)


@router.get("/{case_id}", response_model=CaseOut, summary="One case with document counts")
async def get_case(
    case_id: uuid.UUID,
    principal: Principal = Depends(require_permission("cases:read")),
    session: AsyncSession = Depends(db_session, scope="function"),
) -> CaseOut:
    return await case_service.get(session, principal.organization_id, case_id)


@router.patch(
    "/{case_id}", response_model=CaseOut, summary="Update title, objective, priority, status"
)
async def update_case(
    case_id: uuid.UUID,
    body: CaseUpdate,
    principal: Principal = Depends(require_permission("cases:write")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> CaseOut:
    return await case_service.update(session, principal, case_id, body, meta)


@router.delete(
    "/{case_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a case (hidden from every API; originals are kept)",
)
async def delete_case(
    case_id: uuid.UUID,
    principal: Principal = Depends(require_permission("cases:delete")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> Response:
    await case_service.soft_delete(session, principal, case_id, meta)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def read_limited(upload: UploadFile, max_bytes: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(READ_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            return b"", True
        chunks.append(chunk)
    return b"".join(chunks), False


@router.post(
    "/{case_id}/documents",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload documents or ZIP archives; accepted files are queued for processing",
)
async def upload_documents(
    case_id: uuid.UUID,
    background: BackgroundTasks,
    files: list[UploadFile] = File(
        ..., description="PDF, PNG, JPG, TIFF, DOCX, XLSX, CSV, EML or ZIP"
    ),
    principal: Principal = Depends(require_permission("documents:upload")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> UploadResponse:
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    incoming = []
    for upload in files[:100]:
        data, too_large = await read_limited(upload, max_bytes)
        incoming.append(ingestion.IncomingFile(upload.filename or "unnamed", data, too_large))
    results = await ingestion.upload(session, get_store(), principal, case_id, incoming, meta)
    accepted = [r.document_id for r in results if r.status == "accepted" and r.document_id]
    job = None
    if accepted:
        job = await document_service.create_process_job(session, principal, accepted, "upload")
        # Runs after the request transaction commits, so the worker sees the rows.
        background.add_task(enqueue_processing, principal.organization_id, job.id)
    return UploadResponse(results=results, job_id=job.id if job else None)


@router.get(
    "/{case_id}/documents",
    response_model=list[DocumentOut],
    summary="Documents of a case with stage progress",
)
async def list_case_documents(
    case_id: uuid.UUID,
    principal: Principal = Depends(require_permission("documents:read")),
    session: AsyncSession = Depends(db_session, scope="function"),
) -> list[DocumentOut]:
    return await document_service.list_for_case(session, principal.organization_id, case_id)


@router.post(
    "/{case_id}/process",
    response_model=ProcessResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue every uploaded or failed document of the case",
)
async def process_case(
    case_id: uuid.UUID,
    background: BackgroundTasks,
    principal: Principal = Depends(require_permission("documents:process")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> ProcessResponse:
    job, ids = await document_service.process_case(session, principal, case_id, meta)
    if job is not None:
        background.add_task(enqueue_processing, principal.organization_id, job.id)
    return ProcessResponse(job_id=job.id if job else None, document_ids=ids)
