"""System health, audit log, overview statistics and job endpoints."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, require_permission
from app.core.db import tenant_session
from app.schemas.common import PROBLEM_RESPONSES, Page
from app.schemas.system import AuditLogOut, HealthResponse, JobOut, OverviewStats
from app.services.audit import service as audit_service
from app.services.identity.principal import Principal
from app.services.jobs import service as job_service
from app.services.stats import overview as stats_service
from app.services.system import health as health_service

router = APIRouter(tags=["system"])

SSE_POLL_SECONDS = 0.5
SSE_MAX_SECONDS = 600


@router.get(
    "/system/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse}},
    summary="Database and Redis health",
)
async def health() -> JSONResponse:
    result = await health_service.check()
    code = status.HTTP_200_OK if result.status == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(result.model_dump(), status_code=code)


@router.get(
    "/audit-logs",
    response_model=Page[AuditLogOut],
    responses=PROBLEM_RESPONSES,
    summary="Audit log of the active organization, newest first",
)
async def list_audit_logs(
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None, max_length=20),
    principal: Principal = Depends(require_permission("audit:read")),
    session: AsyncSession = Depends(db_session),
) -> Page[AuditLogOut]:
    return await audit_service.list_for_org(session, principal.organization_id, limit, cursor)


@router.get(
    "/stats/overview",
    response_model=OverviewStats,
    responses=PROBLEM_RESPONSES,
    summary="Overview metrics computed from this organization's records",
)
async def overview(
    principal: Principal = Depends(require_permission("stats:read")),
    session: AsyncSession = Depends(db_session),
) -> OverviewStats:
    return await stats_service.overview(session, principal.organization_id)


def _enqueue_ping(organization_id: uuid.UUID, job_id: uuid.UUID) -> None:
    from app.workers.system_tasks import ping

    ping.delay(str(organization_id), str(job_id))


@router.post(
    "/system/ping-job",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses=PROBLEM_RESPONSES,
    summary="Queue a worker connectivity check (verifies Redis → worker → database)",
)
async def ping_job(
    background: BackgroundTasks,
    principal: Principal = Depends(require_permission("system:ping")),
    session: AsyncSession = Depends(db_session),
) -> JobOut:
    job = await job_service.create_job(
        session, principal.organization_id, "system.ping", created_by=principal.user_id
    )
    # Background tasks run after the request transaction commits, so the worker sees the row.
    background.add_task(_enqueue_ping, principal.organization_id, job.id)
    return JobOut.model_validate(job)


@router.get(
    "/jobs/{job_id}", response_model=JobOut, responses=PROBLEM_RESPONSES, summary="Job state"
)
async def get_job(
    job_id: uuid.UUID,
    principal: Principal = Depends(require_permission("jobs:read")),
    session: AsyncSession = Depends(db_session),
) -> JobOut:
    return JobOut.model_validate(
        await job_service.get_job(session, principal.organization_id, job_id)
    )


def _sse(seq: int, event: str, data: dict[str, object]) -> str:
    return f"id: {seq}\nevent: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def job_event_stream(
    organization_id: uuid.UUID, job_id: uuid.UUID, after_seq: int
) -> AsyncIterator[str]:
    """Stream persisted events with seq > after_seq until the job is terminal."""
    last = after_seq
    loop = asyncio.get_running_loop()
    deadline = loop.time() + SSE_MAX_SECONDS
    while loop.time() < deadline:
        async with tenant_session(organization_id) as session:
            events = await job_service.events_after(session, organization_id, job_id, last)
            job = await job_service.get_job(session, organization_id, job_id)
        for event in events:
            last = event.seq
            yield _sse(
                event.seq,
                event.type,
                {
                    "seq": event.seq,
                    "type": event.type,
                    "data": event.data,
                    "created_at": event.created_at.isoformat(),
                    "job_status": job.status,
                    "progress": job.progress,
                },
            )
        if job_service.is_terminal(job.status) and not events:
            yield "event: end\ndata: {}\n\n"
            return
        if not events:
            yield ": keep-alive\n\n"
        await asyncio.sleep(SSE_POLL_SECONDS)


@router.get(
    "/jobs/{job_id}/events",
    responses={**PROBLEM_RESPONSES, 200: {"content": {"text/event-stream": {}}}},
    summary="Server-sent events for a job; send Last-Event-ID to resume after a reconnect",
)
async def job_events(
    job_id: uuid.UUID,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID", max_length=12),
    principal: Principal = Depends(require_permission("jobs:read")),
    session: AsyncSession = Depends(db_session),
) -> StreamingResponse:
    await job_service.get_job(session, principal.organization_id, job_id)  # 404 across orgs
    after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
    return StreamingResponse(
        job_event_stream(principal.organization_id, job_id, after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
