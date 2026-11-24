"""System tasks. `system.ping` verifies the worker → database path end to end."""

from __future__ import annotations

import asyncio
import socket
import time
import uuid
from typing import Any

from celery import Task
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.storage.s3_store import get_store
from app.models import Job
from app.services.jobs.runner import Outcome, execute_job
from app.services.system.retention import purge_expired
from app.workers.celery_app import celery_app


async def ping_work(session: AsyncSession, job: Job) -> dict[str, Any]:
    start = time.perf_counter()
    await session.execute(text("SELECT 1"))
    return {
        "worker": socket.gethostname(),
        "db_roundtrip_ms": round((time.perf_counter() - start) * 1000, 2),
    }


@celery_app.task(name="system.retention_purge", time_limit=1800, soft_time_limit=1750)
def retention_purge() -> dict[str, Any]:
    return asyncio.run(purge_expired(get_store()))


@celery_app.task(name="system.ping", bind=True, max_retries=None)
def ping(self: Task[Any, Any], organization_id: str, job_id: str) -> str:
    result = asyncio.run(execute_job(uuid.UUID(organization_id), uuid.UUID(job_id), ping_work))
    if result.outcome is Outcome.RETRY:
        raise self.retry(countdown=result.retry_in_seconds)
    return result.outcome.value
