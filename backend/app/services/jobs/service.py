"""Persisted job state machine with an ordered event log."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.models import TERMINAL_STATUSES, Job, JobEvent, JobStatus

# Allowed status transitions. "running -> queued" is a scheduled retry.
ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.FAILED}),
    JobStatus.RUNNING: frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.QUEUED}),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset(),
}


class InvalidTransitionError(Exception):
    pass


def can_transition(current: str, new: str) -> bool:
    try:
        return JobStatus(new) in ALLOWED_TRANSITIONS[JobStatus(current)]
    except ValueError:
        return False


async def append_event(
    session: AsyncSession, job: Job, event_type: str, data: dict[str, Any] | None = None
) -> JobEvent:
    """Append an event with the next sequence number. Callers hold the job row lock."""
    last = await session.scalar(select(func.max(JobEvent.seq)).where(JobEvent.job_id == job.id))
    event = JobEvent(
        job_id=job.id,
        organization_id=job.organization_id,
        seq=(last or 0) + 1,
        type=event_type,
        data=data or {},
    )
    session.add(event)
    await session.flush()
    return event


async def create_job(
    session: AsyncSession,
    organization_id: uuid.UUID,
    kind: str,
    payload: dict[str, Any] | None = None,
    created_by: uuid.UUID | None = None,
    max_attempts: int | None = None,
) -> Job:
    job = Job(
        id=uuid.uuid4(),
        organization_id=organization_id,
        kind=kind,
        status=JobStatus.QUEUED,
        progress=0,
        attempts=0,
        max_attempts=max_attempts or get_settings().job_max_attempts,
        payload=payload or {},
        created_by=created_by,
    )
    session.add(job)
    await session.flush()
    await append_event(session, job, "queued", {"kind": kind})
    return job


async def lock_job(session: AsyncSession, job_id: uuid.UUID) -> Job | None:
    return await session.scalar(select(Job).where(Job.id == job_id).with_for_update())


async def transition(
    session: AsyncSession,
    job: Job,
    new_status: JobStatus,
    *,
    event_type: str | None = None,
    data: dict[str, Any] | None = None,
    progress: int | None = None,
    error: str | None = None,
    result: dict[str, Any] | None = None,
) -> Job:
    if not can_transition(job.status, new_status):
        raise InvalidTransitionError(f"{job.status} -> {new_status}")
    job.status = new_status
    if progress is not None:
        job.progress = max(0, min(100, progress))
    if error is not None:
        job.error = error[:2000]
    if result is not None:
        job.result = result
    await append_event(session, job, event_type or new_status.value, data)
    return job


async def get_job(session: AsyncSession, organization_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    job = await session.scalar(
        select(Job).where(Job.id == job_id, Job.organization_id == organization_id)
    )
    if job is None:
        raise NotFoundError("Job not found.")
    return job


async def events_after(
    session: AsyncSession, organization_id: uuid.UUID, job_id: uuid.UUID, after_seq: int
) -> list[JobEvent]:
    rows = await session.scalars(
        select(JobEvent)
        .where(
            JobEvent.job_id == job_id,
            JobEvent.organization_id == organization_id,
            JobEvent.seq > after_seq,
        )
        .order_by(JobEvent.seq)
    )
    return list(rows)


def is_terminal(status: str) -> bool:
    return status in {s.value for s in TERMINAL_STATUSES}
