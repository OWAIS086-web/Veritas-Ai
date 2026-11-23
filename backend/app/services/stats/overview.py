"""Overview dashboard metrics, computed from persisted rows of one organization."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Date

from app.models import AuditLog, Case, Document, DocumentStatus, Job, JobStatus, OrganizationMember
from app.schemas.system import DailyCount, Metric, OverviewStats
from app.services.findings.service import count_open


async def _count(session: AsyncSession, stmt: object) -> int:
    return int(await session.scalar(stmt) or 0)  # type: ignore[call-overload]


async def overview(session: AsyncSession, organization_id: uuid.UUID) -> OverviewStats:
    now = datetime.now(UTC)
    org = organization_id

    members = await _count(
        session,
        select(func.count())
        .select_from(OrganizationMember)
        .where(OrganizationMember.organization_id == org),
    )
    by_status = dict(
        (
            await session.execute(
                select(Job.status, func.count())
                .where(Job.organization_id == org)
                .group_by(Job.status)
            )
        )
        .tuples()
        .all()
    )
    total = sum(int(v) for v in by_status.values())
    succeeded = int(by_status.get(JobStatus.SUCCEEDED.value, 0))
    failed = int(by_status.get(JobStatus.FAILED.value, 0))
    running = int(by_status.get(JobStatus.RUNNING.value, 0)) + int(
        by_status.get(JobStatus.QUEUED.value, 0)
    )
    finished = succeeded + failed
    success_rate = (
        Metric(value=round(succeeded / finished, 4))
        if finished
        else Metric(value=None, note="No finished jobs yet")
    )

    audit_7d = await _count(
        session,
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.organization_id == org, AuditLog.created_at >= now - timedelta(days=7)),
    )
    start = (now - timedelta(days=13)).date()
    day = cast(func.timezone("UTC", AuditLog.created_at), Date)
    daily_rows = (
        (
            await session.execute(
                select(day, func.count())
                .where(AuditLog.organization_id == org, day >= start)
                .group_by(day)
            )
        )
        .tuples()
        .all()
    )
    daily: dict[date, int] = {d: int(c) for d, c in daily_rows}
    activity = [
        DailyCount(day=start + timedelta(days=i), count=daily.get(start + timedelta(days=i), 0))
        for i in range(14)
    ]

    documents_done = await _count(
        session,
        select(func.count())
        .select_from(Document)
        .join(Case, Case.id == Document.case_id)
        .where(
            Document.organization_id == org,
            Document.status == DocumentStatus.COMPLETED,
            Case.deleted_at.is_(None),
        ),
    )
    review, high = await count_open(session, org)
    open_cases = await _count(
        session,
        select(func.count())
        .select_from(Case)
        .where(Case.organization_id == org, Case.status == "open", Case.deleted_at.is_(None)),
    )

    return OverviewStats(
        members=Metric(value=members),
        jobs_total=Metric(value=total),
        jobs_running=Metric(value=running),
        jobs_failed=Metric(value=failed),
        job_success_rate=success_rate,
        audit_events_7d=Metric(value=audit_7d),
        activity_14d=activity,
        documents_processed=Metric(value=documents_done),
        active_investigations=Metric(value=open_cases),
        findings_requiring_review=Metric(value=review),
        high_priority_findings=Metric(value=high),
    )
