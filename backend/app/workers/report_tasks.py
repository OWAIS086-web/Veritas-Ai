"""Celery task for reports. Idempotent: a finished report is left as it is."""

from __future__ import annotations

import asyncio
import uuid

from app.integrations.storage.s3_store import get_store
from app.services.reporting.service import generate
from app.workers.celery_app import celery_app


@celery_app.task(name="reports.generate", time_limit=600, soft_time_limit=570)
def generate_report(organization_id: str, report_id: str) -> str:
    return asyncio.run(generate(uuid.UUID(organization_id), uuid.UUID(report_id), get_store()))
