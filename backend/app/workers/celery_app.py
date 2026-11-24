"""Celery application. Tasks are idempotent and acknowledged late."""

from __future__ import annotations

from contextvars import Token
from typing import Any

from celery import Celery
from celery.signals import task_postrun, task_prerun

from app.core.config import get_settings
from app.core.logging import configure_logging, task_context, task_context_var

_settings = get_settings()
configure_logging(_settings.log_level)

celery_app = Celery(
    "veritas",
    broker=_settings.broker_url,
    backend=_settings.result_backend,
    include=[
        "app.workers.system_tasks",
        "app.workers.document_tasks",
        "app.workers.comparison_tasks",
        "app.workers.graph_tasks",
        "app.workers.investigation_tasks",
        "app.workers.report_tasks",
        "app.workers.doccompare_tasks",
    ],
)
# Run by the beat embedded in the worker (`celery worker -B`).
celery_app.conf.beat_schedule = {
    "graph-drain-outbox": {"task": "graph.drain_outbox", "schedule": 15.0},
    "graph-reconcile": {"task": "graph.reconcile", "schedule": 600.0},
    "retention-purge": {
        "task": "system.retention_purge",
        "schedule": float(_settings.retention_purge_interval_seconds),
    },
}
_context_tokens: dict[str, Token[dict[str, str] | None]] = {}


@task_prerun.connect
def _bind_log_context(
    task_id: str | None = None, task: Any = None, args: tuple[Any, ...] = (), **_: Any
) -> None:
    """Every log line of a task carries its name, ids and organization (see JsonFormatter)."""
    ctx = task_context(getattr(task, "name", "unknown"), task_id, tuple(args or ()))
    _context_tokens[task_id or ""] = task_context_var.set(ctx)


@task_postrun.connect
def _clear_log_context(task_id: str | None = None, **_: Any) -> None:
    token = _context_tokens.pop(task_id or "", None)
    if token is not None:
        task_context_var.reset(token)


celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=300,
    task_soft_time_limit=270,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    result_expires=3600,
    broker_connection_retry_on_startup=True,
)
app = celery_app
