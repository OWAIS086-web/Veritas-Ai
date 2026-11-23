"""Celery application. Tasks are idempotent and acknowledged late."""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings
from app.core.logging import configure_logging

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
    ],
)
# Run by the beat embedded in the worker (`celery worker -B`).
celery_app.conf.beat_schedule = {
    "graph-drain-outbox": {"task": "graph.drain_outbox", "schedule": 15.0},
    "graph-reconcile": {"task": "graph.reconcile", "schedule": 600.0},
}
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
