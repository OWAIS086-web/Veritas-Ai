"""Reports: request, history, detail, signed download."""

from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, request_meta, require_permission
from app.core.db import tenant_session
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.signing import REPORT_ARTIFACT, InvalidSignatureError, verify
from app.integrations.storage.base import ObjectNotFoundError
from app.integrations.storage.s3_store import get_store
from app.models import Case
from app.schemas.common import PROBLEM_RESPONSES
from app.schemas.reporting import DownloadOut, ReportCreate, ReportDetail, ReportOut
from app.services.audit import service as audit
from app.services.identity.principal import Principal, RequestMeta
from app.services.reporting import service
from app.services.reporting.render import MIME
from app.workers.dispatch import enqueue_report

router = APIRouter(tags=["reports"], responses=PROBLEM_RESPONSES)


@router.post(
    "/cases/{case_id}/reports",
    response_model=ReportOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a report (pdf, docx, json or xlsx); generated and verified in the worker",
)
async def create_report(
    case_id: uuid.UUID,
    body: ReportCreate,
    background: BackgroundTasks,
    principal: Principal = Depends(require_permission("reports:create")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> ReportOut:
    out = await service.create(
        session, principal, case_id, body.format, body.investigation_id, meta
    )
    background.add_task(enqueue_report, principal.organization_id, out.id)
    return out


@router.get(
    "/cases/{case_id}/reports",
    response_model=list[ReportOut],
    summary="Report history of a case: format, status, review status of the findings, creator",
)
async def case_reports(
    case_id: uuid.UUID,
    principal: Principal = Depends(require_permission("reports:read")),
    session: AsyncSession = Depends(db_session, scope="function"),
) -> list[ReportOut]:
    return await service.list_for_case(session, principal.organization_id, case_id)


@router.get(
    "/reports/{report_id}",
    response_model=ReportDetail,
    summary="A report with the verified content every format was rendered from",
)
async def get_report(
    report_id: uuid.UUID,
    principal: Principal = Depends(require_permission("reports:read")),
    session: AsyncSession = Depends(db_session, scope="function"),
) -> ReportDetail:
    return await service.detail(session, principal.organization_id, report_id)


@router.get(
    "/reports/{report_id}/download",
    response_model=DownloadOut,
    summary="A short-lived signed link to the report file (audited)",
)
async def download(
    report_id: uuid.UUID,
    principal: Principal = Depends(require_permission("reports:read")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> DownloadOut:
    return await service.download_link(session, principal, report_id, meta)


@router.get(
    "/report-files/{token}",
    responses={
        200: {"content": {"application/octet-stream": {}}},
        403: {"description": "Invalid or expired link"},
    },
    summary="Serve a report file through a signed link (no bearer token; the link expires)",
)
async def report_file(
    token: str = Path(max_length=400),
    meta: RequestMeta = Depends(request_meta),
) -> Response:
    try:
        grant = verify(token)
    except InvalidSignatureError as exc:
        raise PermissionDeniedError("This file link is invalid or has expired.") from exc
    if grant.artifact != REPORT_ARTIFACT:
        raise PermissionDeniedError("This file link is invalid or has expired.")
    org = grant.organization_id
    async with tenant_session(org) as s:
        report = await service.get_report(s, org, grant.document_id)
        if report.status != "completed" or not report.storage_key:
            raise NotFoundError("Report file not found.")
        title = await s.scalar(select(Case.title).where(Case.id == report.case_id)) or "case"
        await audit.record(
            s,
            "report.download",
            organization_id=org,
            resource_type="report",
            resource_id=report.id,
            meta=meta,
            metadata={"via": "signed_link", "format": report.format},
        )
        key, digest, fmt = report.storage_key, report.sha256, report.format
        name = service.file_name(title, report)
    try:
        data = await get_store().get(key)
    except ObjectNotFoundError as exc:
        raise NotFoundError("Report file not found.") from exc
    if hashlib.sha256(data).hexdigest() != digest:
        # The stored file no longer matches the hash recorded at generation.
        raise NotFoundError("Report file failed its integrity check.")
    return Response(
        content=data,
        media_type=MIME[fmt],
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "X-Report-SHA256": digest,
        },
    )
