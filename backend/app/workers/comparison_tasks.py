"""Celery task that runs the cross-document comparison of one case."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from celery import Task
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job
from app.services.comparison.persist import run_comparison
from app.services.graph.service import rebuild_case_graph
from app.services.jobs.runner import Outcome, execute_job
from app.workers.celery_app import celery_app


async def _run(organization_id: uuid.UUID, job_id: uuid.UUID) -> Outcome:
    async def work(session: AsyncSession, job: Job) -> dict[str, Any]:
        case_id = uuid.UUID(str(job.payload["case_id"]))
        summary = await run_comparison(session, organization_id, case_id)
        summary["graph"] = await rebuild_case_graph(session, organization_id, case_id)
        return summary

    result = await execute_job(organization_id, job_id, work)
    return result.outcome


@celery_app.task(name="cases.compare", bind=True, max_retries=None)
def compare_case(self: Task[Any, Any], organization_id: str, job_id: str) -> str:
    outcome = asyncio.run(_run(uuid.UUID(organization_id), uuid.UUID(job_id)))
    if outcome is Outcome.RETRY:
        raise self.retry(countdown=10)
    return outcome.value
