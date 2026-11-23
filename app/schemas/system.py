"""System, job, audit and statistics schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from app.schemas.common import ApiModel


class ComponentHealth(ApiModel):
    status: Literal["ok", "error"]
    detail: str | None = None


class GraphSyncHealth(ApiModel):
    """The derived evidence graph. Optional: it doesn't change the overall status, because the
    API serves graphs from Postgres when Neo4j is down."""

    status: Literal["ok", "error", "not_configured"]
    detail: str | None = None
    outbox_pending: int = 0
    outbox_dead: int = 0


class HealthResponse(ApiModel):
    status: Literal["ok", "degraded"]
    components: dict[str, ComponentHealth]
    graph: GraphSyncHealth | None = None


class JobOut(ApiModel):
    id: uuid.UUID
    kind: str
    status: str
    progress: int
    attempts: int
    max_attempts: int
    error: str | None
    result: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class JobEventOut(ApiModel):
    seq: int
    type: str
    data: dict[str, Any]
    created_at: datetime


class AuditLogOut(ApiModel):
    id: int
    action: str
    resource_type: str | None
    resource_id: str | None
    actor_user_id: uuid.UUID | None
    actor_email: str | None = None
    ip: str | None
    created_at: datetime
    metadata: dict[str, Any]


class Metric(ApiModel):
    """A dashboard metric. `available=False` means its module is not built yet."""

    value: float | int | None
    available: bool = True
    note: str | None = None


class DailyCount(ApiModel):
    day: date
    count: int


class OverviewStats(ApiModel):
    members: Metric
    jobs_total: Metric
    jobs_running: Metric
    jobs_failed: Metric
    job_success_rate: Metric
    audit_events_7d: Metric
    activity_14d: list[DailyCount]
    documents_processed: Metric
    active_investigations: Metric
    findings_requiring_review: Metric
    high_priority_findings: Metric
