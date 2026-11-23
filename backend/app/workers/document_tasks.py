"""Celery task that runs the document pipeline for a processing job."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from celery import Task

from app.integrations.storage.s3_store import get_store
from app.services.jobs.runner import Emitter, Outcome, execute_streaming_job
from app.workers.celery_app import celery_app
from app.workflows.document_pipeline import process_batch as run_batch


async def _run(organization_id: uuid.UUID, job_id: uuid.UUID) -> Outcome:
    async def work(payload: dict[str, Any], emit: Emitter) -> dict[str, Any]:
        return await run_batch(organization_id, payload, emit, get_store())

    result = await execute_streaming_job(organization_id, job_id, work)
    return result.outcome


@celery_app.task(
    name="documents.process_batch",
    bind=True,
    max_retries=None,
    time_limit=4 * 3600,
    soft_time_limit=4 * 3600 - 60,
)
def process_batch(self: Task[Any, Any], organization_id: str, job_id: str) -> str:
    outcome = asyncio.run(_run(uuid.UUID(organization_id), uuid.UUID(job_id)))
    if outcome is Outcome.RETRY:
        raise self.retry(countdown=10)
    return outcome.value
