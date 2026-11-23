"""Celery tasks for original-versus-test document comparisons. Both are idempotent."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from celery import Task

from app.integrations.storage.s3_store import get_store
from app.services.doccompare.run import (
    fail_comparison,
    generate_export,
    queued_exports,
    run_comparison,
)
from app.workers.celery_app import celery_app

WAIT_SECONDS = 10
MAX_WAITS = 180  # about 30 minutes for both documents to finish processing


async def _run_and_export(org: uuid.UUID, cid: uuid.UUID) -> str:
    store = get_store()
    result = await run_comparison(org, cid, store)
    if result == "completed":
        for export_id in await queued_exports(org, cid):
            await generate_export(org, export_id, store)
    return result


async def _give_up(org: uuid.UUID, cid: uuid.UUID) -> None:
    await fail_comparison(org, cid, "The documents were not processed within 30 minutes.")


@celery_app.task(
    name="doccompare.run", bind=True, max_retries=MAX_WAITS, time_limit=1800, soft_time_limit=1750
)
def run(self: Task[Any, Any], organization_id: str, comparison_id: str) -> str:
    org, cid = uuid.UUID(organization_id), uuid.UUID(comparison_id)
    result = asyncio.run(_run_and_export(org, cid))
    if result == "waiting":
        if self.request.retries >= MAX_WAITS:
            asyncio.run(_give_up(org, cid))
            return "failed"
        raise self.retry(countdown=WAIT_SECONDS)
    return result


@celery_app.task(name="doccompare.export", time_limit=600, soft_time_limit=570)
def export(organization_id: str, export_id: str) -> str:
    return asyncio.run(
        generate_export(uuid.UUID(organization_id), uuid.UUID(export_id), get_store())
    )
