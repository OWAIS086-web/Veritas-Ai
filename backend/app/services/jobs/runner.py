"""Run job work with idempotency, bounded retries and persisted state.

Celery tasks call `execute_job`. Each attempt runs the work in its own transaction:
- an already terminal job is skipped (safe re-delivery after a worker crash);
- a failure below `max_attempts` returns RETRY with a backoff delay;
- a failure at `max_attempts` marks the job failed.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import tenant_session
from app.core.logging import get_logger
from app.models import Job, JobStatus
from app.services.jobs.service import append_event, is_terminal, lock_job, transition

logger = get_logger(__name__)
Work = Callable[[AsyncSession, Job], Awaitable[dict[str, Any]]]


class Outcome(StrEnum):
    SUCCEEDED = "succeeded"
    RETRY = "retry"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class RunResult:
    outcome: Outcome
    retry_in_seconds: int | None = None


def backoff_seconds(attempt: int) -> int:
    return int(min(60, 2**attempt))


async def _start(organization_id: uuid.UUID, job_id: uuid.UUID) -> int | None:
    async with tenant_session(organization_id) as session:
        job = await lock_job(session, job_id)
        if job is None or is_terminal(job.status):
            return None
        if job.status == JobStatus.RUNNING:
            # Re-delivered after a crash mid-run: count it as a new attempt.
            await transition(session, job, JobStatus.QUEUED, event_type="redelivered")
        job.attempts += 1
        await transition(
            session,
            job,
            JobStatus.RUNNING,
            event_type="started",
            data={"attempt": job.attempts},
            progress=5,
        )
        return job.attempts


class Emitter(Protocol):
    async def __call__(
        self, event_type: str, data: dict[str, Any], progress: int | None = None
    ) -> None: ...


StreamingWork = Callable[[dict[str, Any], Emitter], Awaitable[dict[str, Any]]]


async def execute_streaming_job(
    organization_id: uuid.UUID, job_id: uuid.UUID, work: StreamingWork
) -> RunResult:
    """Run long work without holding a transaction. Each emitted event commits on its own,
    so the SSE stream shows progress while the work runs. Same retry semantics as
    execute_job; the work itself must be idempotent (document stages are)."""
    attempt = await _start(organization_id, job_id)
    if attempt is None:
        return RunResult(Outcome.SKIPPED)
    async with tenant_session(organization_id) as session:
        job = await lock_job(session, job_id)
        payload = dict(job.payload) if job else {}

    async def emit(event_type: str, data: dict[str, Any], progress: int | None = None) -> None:
        async with tenant_session(organization_id) as s:
            current = await lock_job(s, job_id)
            if current is None or is_terminal(current.status):
                return
            if progress is not None:
                current.progress = max(current.progress, min(99, progress))
            await append_event(s, current, event_type, data)

    try:
        result = await work(payload, emit)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "job_attempt_failed",
            extra={"job": str(job_id), "attempt": attempt, "error": type(exc).__name__},
        )
        async with tenant_session(organization_id) as session:
            job = await lock_job(session, job_id)
            if job is None or is_terminal(job.status):
                return RunResult(Outcome.SKIPPED)
            if job.attempts < job.max_attempts:
                delay = backoff_seconds(job.attempts)
                await transition(
                    session,
                    job,
                    JobStatus.QUEUED,
                    event_type="retry_scheduled",
                    data={"attempt": attempt, "error": message[:500], "retry_in_s": delay},
                )
                return RunResult(Outcome.RETRY, retry_in_seconds=delay)
            await transition(
                session,
                job,
                JobStatus.FAILED,
                error=message,
                data={"attempt": attempt, "error": message[:500]},
            )
        return RunResult(Outcome.FAILED)
    async with tenant_session(organization_id) as session:
        job = await lock_job(session, job_id)
        if job is None or is_terminal(job.status):
            return RunResult(Outcome.SKIPPED)
        await transition(
            session,
            job,
            JobStatus.SUCCEEDED,
            progress=100,
            result=result,
            data={"attempt": attempt},
        )
    return RunResult(Outcome.SUCCEEDED)


async def execute_job(organization_id: uuid.UUID, job_id: uuid.UUID, work: Work) -> RunResult:
    attempt = await _start(organization_id, job_id)
    if attempt is None:
        return RunResult(Outcome.SKIPPED)
    try:
        async with tenant_session(organization_id) as session:
            job = await lock_job(session, job_id)
            if job is None:
                return RunResult(Outcome.SKIPPED)
            result = await work(session, job)
            await transition(
                session,
                job,
                JobStatus.SUCCEEDED,
                progress=100,
                result=result,
                data={"attempt": attempt},
            )
        return RunResult(Outcome.SUCCEEDED)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "job_attempt_failed",
            extra={"job": str(job_id), "attempt": attempt, "error": type(exc).__name__},
        )
        async with tenant_session(organization_id) as session:
            job = await lock_job(session, job_id)
            if job is None or is_terminal(job.status):
                return RunResult(Outcome.SKIPPED)
            if job.attempts < job.max_attempts:
                delay = backoff_seconds(job.attempts)
                await transition(
                    session,
                    job,
                    JobStatus.QUEUED,
                    event_type="retry_scheduled",
                    data={"attempt": attempt, "error": message[:500], "retry_in_s": delay},
                )
                return RunResult(Outcome.RETRY, retry_in_seconds=delay)
            await transition(
                session,
                job,
                JobStatus.FAILED,
                error=message,
                data={"attempt": attempt, "error": message[:500]},
            )
        return RunResult(Outcome.FAILED)
