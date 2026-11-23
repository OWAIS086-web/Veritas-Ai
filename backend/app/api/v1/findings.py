"""Cross-document comparison and findings review."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, request_meta, require_permission
from app.schemas.common import PROBLEM_RESPONSES, Page, Problem
from app.schemas.findings import (
    AssigneeChange,
    CommentCreate,
    CommentOut,
    CompareResponse,
    EvidenceOut,
    FindingDetail,
    FindingSummary,
    StatusChange,
)
from app.schemas.investigations import EvidenceRequestCreate, EvidenceRequestOut
from app.services.comparison import service as comparison
from app.services.findings import service as findings
from app.services.identity.principal import Principal, RequestMeta
from app.workers.dispatch import enqueue_comparison

router = APIRouter(tags=["findings"], responses=PROBLEM_RESPONSES)

STATUS_PATTERN = "^(new|under_review|confirmed_observation|needs_more_evidence|dismissed|resolved)$"


@router.post(
    "/cases/{case_id}/compare",
    response_model=CompareResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a cross-document comparison of the case's processed documents",
)
async def compare_case(
    case_id: uuid.UUID,
    background: BackgroundTasks,
    principal: Principal = Depends(require_permission("findings:run")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> CompareResponse:
    job = await comparison.start_comparison(session, principal, case_id, meta)
    # Runs after the request transaction commits, so the worker sees the job row.
    background.add_task(enqueue_comparison, principal.organization_id, job.id)
    return CompareResponse(job_id=job.id)


@router.get(
    "/cases/{case_id}/findings",
    response_model=list[FindingSummary],
    summary="Findings of one case, most severe first",
)
async def case_findings(
    case_id: uuid.UUID,
    include_inactive: bool = Query(False, description="Include findings no longer detected"),
    principal: Principal = Depends(require_permission("findings:read")),
    session: AsyncSession = Depends(db_session, scope="function"),
) -> list[FindingSummary]:
    return await findings.list_for_case(
        session, principal.organization_id, case_id, include_inactive
    )


@router.get("/findings", response_model=Page[FindingSummary], summary="Findings Center list")
async def list_findings(
    case_id: uuid.UUID | None = None,
    status_filter: str | None = Query(None, alias="status", pattern=STATUS_PATTERN),
    severity: str | None = Query(None, pattern="^(info|low|medium|high)$"),
    priority: str | None = Query(None, pattern="^(low|medium|high)$"),
    finding_type: str | None = Query(None, alias="type", max_length=40, pattern="^[a-z_]+$"),
    include_inactive: bool = False,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None, max_length=100),
    principal: Principal = Depends(require_permission("findings:read")),
    session: AsyncSession = Depends(db_session, scope="function"),
) -> Page[FindingSummary]:
    return await findings.list_findings(
        session,
        principal.organization_id,
        case_id=case_id,
        status=status_filter,
        severity=severity,
        priority=priority,
        finding_type=finding_type,
        include_inactive=include_inactive,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/findings/{finding_id}",
    response_model=FindingDetail,
    summary="One finding with evidence, decisions and comments",
)
async def get_finding(
    finding_id: uuid.UUID,
    principal: Principal = Depends(require_permission("findings:read")),
    session: AsyncSession = Depends(db_session, scope="function"),
) -> FindingDetail:
    return await findings.get(session, principal.organization_id, finding_id)


@router.get(
    "/findings/{finding_id}/evidence",
    response_model=list[EvidenceOut],
    summary="Evidence items of a finding, each linked to its extracted field",
)
async def finding_evidence(
    finding_id: uuid.UUID,
    principal: Principal = Depends(require_permission("findings:read")),
    session: AsyncSession = Depends(db_session, scope="function"),
) -> list[EvidenceOut]:
    return await findings.evidence(session, principal.organization_id, finding_id)


@router.patch(
    "/findings/{finding_id}/status",
    response_model=FindingDetail,
    summary="Record a review decision (409 when confirming a finding without evidence)",
    responses={409: {"model": Problem, "description": "Not allowed in the current state"}},
)
async def change_status(
    finding_id: uuid.UUID,
    body: StatusChange,
    principal: Principal = Depends(require_permission("findings:review")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> FindingDetail:
    return await findings.change_status(session, principal, finding_id, body, meta)


@router.patch(
    "/findings/{finding_id}/assignee",
    response_model=FindingDetail,
    summary="Assign the finding to an investigator of the organization (null clears it)",
)
async def assign(
    finding_id: uuid.UUID,
    body: AssigneeChange,
    principal: Principal = Depends(require_permission("findings:assign")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> FindingDetail:
    return await findings.assign(session, principal, finding_id, body.user_id, meta)


@router.post(
    "/findings/{finding_id}/evidence-requests",
    response_model=EvidenceRequestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Request additional documents for this finding (shown on the case)",
)
async def request_evidence(
    finding_id: uuid.UUID,
    body: EvidenceRequestCreate,
    principal: Principal = Depends(require_permission("findings:comment")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> EvidenceRequestOut:
    return await findings.request_evidence(session, principal, finding_id, body, meta)


@router.post(
    "/findings/{finding_id}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add an investigator comment",
)
async def add_comment(
    finding_id: uuid.UUID,
    body: CommentCreate,
    principal: Principal = Depends(require_permission("findings:comment")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> CommentOut:
    return await findings.add_comment(session, principal, finding_id, body, meta)
