"""Autonomous investigations: start, read, stream events, approve, request evidence."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, Depends, Header, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, request_meta, require_permission
from app.core.db import tenant_session
from app.schemas.common import PROBLEM_RESPONSES
from app.schemas.investigations import (
    EvidenceRequestCreate,
    EvidenceRequestOut,
    InvestigateRequest,
    InvestigationDetail,
    InvestigationOut,
)
from app.services.identity.principal import Principal, RequestMeta
from app.services.investigations import service
from app.workers.dispatch import enqueue_investigation

router = APIRouter(tags=["investigations"], responses=PROBLEM_RESPONSES)
SSE_POLL_SECONDS = 0.5
SSE_MAX_SECONDS = 600


@router.post(
    "/cases/{case_id}/investigate",
    response_model=InvestigationOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start an autonomous investigation of the case (runs in the worker)",
)
async def investigate(
    case_id: uuid.UUID,
    body: InvestigateRequest,
    background: BackgroundTasks,
    principal: Principal = Depends(require_permission("investigations:run")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> InvestigationOut:
    out = await service.start(session, principal, case_id, body.objective, meta)
    background.add_task(enqueue_investigation, principal.organization_id, out.id)
    return out


@router.get(
    "/cases/{case_id}/investigations",
    response_model=list[InvestigationOut],
    summary="Investigations of a case, newest first",
)
async def case_investigations(
    case_id: uuid.UUID,
    principal: Principal = Depends(require_permission("investigations:read")),
    session: AsyncSession = Depends(db_session, scope="function"),
) -> list[InvestigationOut]:
    return await service.list_for_case(session, principal.organization_id, case_id)


@router.get(
    "/cases/{case_id}/evidence-requests",
    response_model=list[EvidenceRequestOut],
    summary="Evidence requested by reviewers for this case",
)
async def case_evidence_requests(
    case_id: uuid.UUID,
    principal: Principal = Depends(require_permission("investigations:read")),
    session: AsyncSession = Depends(db_session, scope="function"),
) -> list[EvidenceRequestOut]:
    return await service.evidence_requests(session, principal.organization_id, case_id)


@router.get(
    "/investigations/{investigation_id}",
    response_model=InvestigationDetail,
    summary="State of an investigation: status, budget use, agent runs and validated outputs",
)
async def get_investigation(
    investigation_id: uuid.UUID,
    principal: Principal = Depends(require_permission("investigations:read")),
    session: AsyncSession = Depends(db_session, scope="function"),
) -> InvestigationDetail:
    return await service.detail(session, principal.organization_id, investigation_id)


def _sse(seq: int, event: str, data: dict[str, object]) -> str:
    return f"id: {seq}\nevent: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def _event_stream(
    organization_id: uuid.UUID, investigation_id: uuid.UUID, after_seq: int
) -> AsyncIterator[str]:
    """Persisted agent events with seq > after_seq, until the investigation pauses or ends."""
    last = after_seq
    loop = asyncio.get_running_loop()
    deadline = loop.time() + SSE_MAX_SECONDS
    while loop.time() < deadline:
        async with tenant_session(organization_id) as s:
            events = await service.events_after(s, organization_id, investigation_id, last)
            inv = await service.get_investigation(s, organization_id, investigation_id)
        for e in events:
            last = e.seq
            yield _sse(
                e.seq,
                e.type,
                {
                    "seq": e.seq,
                    "agent": e.agent,
                    "type": e.type,
                    "data": e.data,
                    "created_at": e.created_at.isoformat(),
                    "status": inv.status,
                },
            )
        if inv.status in service.STREAM_PAUSED and not events:
            yield "event: end\ndata: {}\n\n"
            return
        if not events:
            yield ": keep-alive\n\n"
        await asyncio.sleep(SSE_POLL_SECONDS)


@router.get(
    "/investigations/{investigation_id}/events",
    responses={200: {"content": {"text/event-stream": {}}}},
    summary="Server-sent agent events; send Last-Event-ID to resume after a reconnect",
)
async def investigation_events(
    investigation_id: uuid.UUID,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID", max_length=12),
    principal: Principal = Depends(require_permission("investigations:read")),
    session: AsyncSession = Depends(db_session, scope="function"),
) -> StreamingResponse:
    await service.get_investigation(session, principal.organization_id, investigation_id)
    after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
    return StreamingResponse(
        _event_stream(principal.organization_id, investigation_id, after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/investigations/{investigation_id}/approve",
    response_model=InvestigationOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Approve an investigation awaiting review; the report step then runs",
)
async def approve(
    investigation_id: uuid.UUID,
    background: BackgroundTasks,
    principal: Principal = Depends(require_permission("findings:review")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> InvestigationOut:
    out = await service.approve(session, principal, investigation_id, meta)
    background.add_task(enqueue_investigation, principal.organization_id, out.id)
    return out


@router.post(
    "/investigations/{investigation_id}/request-evidence",
    response_model=EvidenceRequestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a request for more documents; it is shown on the case",
)
async def request_evidence(
    investigation_id: uuid.UUID,
    body: EvidenceRequestCreate,
    principal: Principal = Depends(require_permission("findings:comment")),
    session: AsyncSession = Depends(db_session, scope="function"),
    meta: RequestMeta = Depends(request_meta),
) -> EvidenceRequestOut:
    return await service.request_evidence(
        session, principal, investigation_id, body.document_types, body.note, meta
    )
