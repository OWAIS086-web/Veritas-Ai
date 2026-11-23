"""Document comparison lab: original-versus-test comparisons, human review, exports and the
signed export download."""

from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Path, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, request_meta, require_permission
from app.api.v1.cases import read_limited
from app.core.config import get_settings
from app.core.db import tenant_session
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.signing import COMPARISON_EXPORT_ARTIFACT, InvalidSignatureError, verify
from app.integrations.llm.openai_compat import vision_status
from app.integrations.storage.base import ObjectNotFoundError
from app.integrations.storage.s3_store import get_store
from app.schemas.common import PROBLEM_RESPONSES
from app.schemas.doccompare import (
    ComparisonCreate,
    ComparisonDetail,
    ComparisonExportOut,
    ComparisonFindingOut,
    ComparisonOut,
    ComparisonUploadOut,
    ExportCreate,
    ReviewEntryOut,
    ReviewIn,
    VlmStatusOut,
)
from app.schemas.reporting import DownloadOut
from app.services.audit import service as audit
from app.services.doccompare import service
from app.services.documents import service as document_service
from app.services.identity.principal import Principal, RequestMeta
from app.services.ingestion import service as ingestion
from app.workers.dispatch import (
    enqueue_comparison_export,
    enqueue_document_comparison,
    enqueue_processing,
)

router = APIRouter(tags=["document comparison"], responses=PROBLEM_RESPONSES)


@router.post(
    "/cases/{case_id}/comparisons",
    response_model=ComparisonOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Compare a test document against an original (both documents of the case)",
)
async def create_comparison(
    case_id: uuid.UUID,
    body: ComparisonCreate,
    background: BackgroundTasks,
    principal: Principal = Depends(require_permission("comparisons:run")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> ComparisonOut:
    out = await service.create(
        session, principal, case_id, body.original_document_id, body.test_document_id, meta
    )
    background.add_task(enqueue_document_comparison, principal.organization_id, out.id)
    return out


@router.post(
    "/cases/{case_id}/comparisons/upload",
    response_model=ComparisonUploadOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload an original and a test file and compare them once both are processed",
)
async def upload_comparison(
    case_id: uuid.UUID,
    background: BackgroundTasks,
    original: UploadFile = File(..., description="The reference document (PDF, PNG, JPEG, TIFF)"),
    test: UploadFile = File(..., description="The document examined for differences"),
    principal: Principal = Depends(require_permission("comparisons:run")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> ComparisonUploadOut:
    if "documents:upload" not in principal.permissions:
        raise PermissionDeniedError("Your role does not allow 'documents:upload'.")
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    files = []
    for upload in (original, test):
        data, too_large = await read_limited(upload, max_bytes)
        files.append(ingestion.IncomingFile(upload.filename or "unnamed", data, too_large))
    out, accepted = await service.upload_and_create(
        session, get_store(), principal, case_id, files[0], files[1], meta
    )
    if accepted:
        job = await document_service.create_process_job(
            session, principal, accepted, "comparison.upload"
        )
        out.job_id = job.id
        background.add_task(enqueue_processing, principal.organization_id, job.id)
    # The comparison task waits until both documents finish processing.
    background.add_task(enqueue_document_comparison, principal.organization_id, out.comparison.id)
    return out


@router.get(
    "/cases/{case_id}/comparisons",
    response_model=list[ComparisonOut],
    summary="Comparisons of a case with their status and progress",
)
async def case_comparisons(
    case_id: uuid.UUID,
    principal: Principal = Depends(require_permission("comparisons:read")),
    session: AsyncSession = Depends(db_session, scope="function"),
) -> list[ComparisonOut]:
    return await service.list_for_case(session, principal.organization_id, case_id)


@router.get(
    "/comparisons/{comparison_id}",
    response_model=ComparisonDetail,
    summary="A comparison with its summary, findings (regions on both documents) and exports",
)
async def get_comparison(
    comparison_id: uuid.UUID,
    principal: Principal = Depends(require_permission("comparisons:read")),
    session: AsyncSession = Depends(db_session, scope="function"),
) -> ComparisonDetail:
    return await service.detail(session, principal.organization_id, comparison_id)


@router.post(
    "/comparisons/{comparison_id}/retry",
    response_model=ComparisonOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run a failed comparison again",
)
async def retry_comparison(
    comparison_id: uuid.UUID,
    background: BackgroundTasks,
    principal: Principal = Depends(require_permission("comparisons:run")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> ComparisonOut:
    out = await service.retry(session, principal, comparison_id, meta)
    background.add_task(enqueue_document_comparison, principal.organization_id, out.id)
    return out


@router.patch(
    "/comparisons/{comparison_id}/findings/{finding_id}/review",
    response_model=ComparisonFindingOut,
    summary="Record a human review decision (a note is required to confirm or dismiss)",
)
async def review_finding(
    comparison_id: uuid.UUID,
    finding_id: uuid.UUID,
    body: ReviewIn,
    principal: Principal = Depends(require_permission("findings:review")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> ComparisonFindingOut:
    return await service.review(session, principal, comparison_id, finding_id, body, meta)


@router.get(
    "/comparisons/{comparison_id}/findings/{finding_id}/reviews",
    response_model=list[ReviewEntryOut],
    summary="The append-only review history of a finding",
)
async def finding_reviews(
    comparison_id: uuid.UUID,
    finding_id: uuid.UUID,
    principal: Principal = Depends(require_permission("comparisons:read")),
    session: AsyncSession = Depends(db_session, scope="function"),
) -> list[ReviewEntryOut]:
    return await service.review_history(
        session, principal.organization_id, comparison_id, finding_id
    )


@router.post(
    "/comparisons/{comparison_id}/exports",
    response_model=ComparisonExportOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate an export again (e.g. after review): annotated PDF or images, report, JSON",
)
async def create_export(
    comparison_id: uuid.UUID,
    body: ExportCreate,
    background: BackgroundTasks,
    principal: Principal = Depends(require_permission("comparisons:run")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> ComparisonExportOut:
    out = await service.request_export(session, principal, comparison_id, body.kind, meta)
    background.add_task(enqueue_comparison_export, principal.organization_id, out.id)
    return out


@router.get(
    "/comparisons/{comparison_id}/exports",
    response_model=list[ComparisonExportOut],
    summary="Exports of a comparison, newest first",
)
async def list_exports(
    comparison_id: uuid.UUID,
    principal: Principal = Depends(require_permission("comparisons:read")),
    session: AsyncSession = Depends(db_session, scope="function"),
) -> list[ComparisonExportOut]:
    return await service.list_exports(session, principal.organization_id, comparison_id)


@router.get(
    "/comparison-exports/{export_id}/download",
    response_model=DownloadOut,
    summary="A short-lived signed link to an export file (audited)",
)
async def export_download(
    export_id: uuid.UUID,
    principal: Principal = Depends(require_permission("comparisons:read")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> DownloadOut:
    return await service.download_link(session, principal, export_id, meta)


@router.get(
    "/comparison-files/{token}",
    responses={
        200: {"content": {"application/octet-stream": {}}},
        403: {"description": "Invalid or expired link"},
    },
    summary="Serve a comparison export through a signed link (no bearer token; it expires)",
)
async def comparison_file(
    token: str = Path(max_length=400),
    meta: RequestMeta = Depends(request_meta),
) -> Response:
    try:
        grant = verify(token)
    except InvalidSignatureError as exc:
        raise PermissionDeniedError("This file link is invalid or has expired.") from exc
    if grant.artifact != COMPARISON_EXPORT_ARTIFACT:
        raise PermissionDeniedError("This file link is invalid or has expired.")
    org = grant.organization_id
    async with tenant_session(org) as s:
        e = await service.get_export(s, org, grant.document_id)
        if e.status != "completed" or not e.storage_key or not e.sha256:
            raise NotFoundError("Export file not found.")
        await audit.record(
            s,
            "comparison.export_download",
            organization_id=org,
            resource_type="comparison_export",
            resource_id=e.id,
            meta=meta,
            metadata={"via": "signed_link", "kind": e.kind},
        )
        key, digest, name = e.storage_key, e.sha256, service.export_file_name(e)
        mime, _ = service.EXPORT_MIME[e.kind]
    try:
        data = await get_store().get(key)
    except ObjectNotFoundError as exc:
        raise NotFoundError("Export file not found.") from exc
    if hashlib.sha256(data).hexdigest() != digest:
        raise NotFoundError("Export file failed its integrity check.")
    return Response(
        content=data,
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "X-Export-SHA256": digest,
        },
    )


@router.get(
    "/system/vlm-status",
    response_model=VlmStatusOut,
    summary="Is the vision model (VERITAS_VLM_MODEL) configured and reachable? No document data",
)
async def vlm_status(
    principal: Principal = Depends(require_permission("comparisons:read")),
) -> VlmStatusOut:
    st = await vision_status()
    return VlmStatusOut(enabled=get_settings().comparison_vlm_enabled, **st)
