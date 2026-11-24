"""Operational metrics for administrators: broker queue depths (global counts only) and this
organization's document-stage outcomes and mean durations, from `document_stages`."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import DocumentStage
from app.schemas.system import MetricsOut, QueueDepth, StageMetrics

QUEUES = ("celery",)


async def _queues() -> list[QueueDepth]:
    redis = Redis.from_url(get_settings().broker_url, socket_connect_timeout=2, socket_timeout=2)
    out = []
    try:
        for name in QUEUES:
            try:
                out.append(QueueDepth(queue=name, waiting=int(await redis.llen(name))))
            except RedisError:
                out.append(QueueDepth(queue=name, waiting=None))
    finally:
        await redis.aclose()
    return out


async def collect(s: AsyncSession, org: uuid.UUID) -> MetricsOut:
    seconds = func.extract("epoch", DocumentStage.finished_at - DocumentStage.started_at)
    rows = await s.execute(
        select(
            DocumentStage.stage,
            func.count().filter(DocumentStage.status == "succeeded"),
            func.count().filter(DocumentStage.status == "failed"),
            func.count().filter(DocumentStage.status.notin_(["succeeded", "failed"])),
            func.avg(case((DocumentStage.status == "succeeded", seconds), else_=None)),
        )
        .where(DocumentStage.organization_id == org)
        .group_by(DocumentStage.stage)
        .order_by(DocumentStage.stage)
    )
    stages = [
        StageMetrics(
            stage=stage,
            succeeded=int(ok),
            failed=int(bad),
            other=int(rest),
            mean_seconds=round(float(mean), 3) if mean is not None else None,
        )
        for stage, ok, bad, rest, mean in rows
    ]
    return MetricsOut(generated_at=datetime.now(UTC), queues=await _queues(), stages=stages)
