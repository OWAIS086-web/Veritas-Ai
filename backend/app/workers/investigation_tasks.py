"""Celery task for investigations. Idempotent: it advances the investigation from its
persisted state and checkpoints, and does nothing for a paused or finished one."""

from __future__ import annotations

import asyncio
import uuid

from app.core.config import get_settings
from app.services.investigations.run import run_investigation
from app.workers.celery_app import celery_app

_LIMIT = get_settings().investigation_timeout_seconds + 120


@celery_app.task(name="investigations.run", time_limit=_LIMIT, soft_time_limit=_LIMIT - 30)
def run(organization_id: str, investigation_id: str) -> str:
    return asyncio.run(run_investigation(uuid.UUID(organization_id), uuid.UUID(investigation_id)))
