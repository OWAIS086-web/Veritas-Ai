"""System, job, audit and statistics schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field

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
    services: dict[str, ComponentHealth] = Field(
        default_factory=dict,
        description=(
            "Object storage and worker liveness (Celery ping). Reported, but they don't change "
            "`status`: the API itself still serves reads without them, and the container "
            "health check uses `status`."
        ),
    )


class QueueDepth(ApiModel):
    queue: str
    waiting: int | None = Field(description="Tasks waiting in the broker; null if unreadable")


class StageMetrics(ApiModel):
    stage: str
    succeeded: int
    failed: int
    other: int
    mean_seconds: float | None = Field(description="Mean duration of succeeded runs")


class MetricsOut(ApiModel):
    generated_at: datetime
    queues: list[QueueDepth]
    stages: list[StageMetrics] = Field(description="This organization's document stages")


class ModelStatus(ApiModel):
    role: Literal["text", "vision", "fallback"]
    model: str
    available: bool | None = Field(description="Listed by the endpoint; null if unreachable")


class ModelsOut(ApiModel):
    provider: Literal["openai_compatible"] = "openai_compatible"
    configured: bool
    endpoint_host: str | None = Field(description="Host only; never the key or full URL")
    api_key_set: bool
    reachable: bool
    error: str | None
    models: list[ModelStatus]
    embeddings: Literal["not_built"] = "not_built"


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
