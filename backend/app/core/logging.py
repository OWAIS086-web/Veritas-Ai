"""Structured JSON logging with request/job correlation ids."""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
job_id_var: ContextVar[str | None] = ContextVar("job_id", default=None)
org_id_var: ContextVar[str | None] = ContextVar("organization_id", default=None)
# Worker tasks: the task name, Celery task id and the id of what the task works on.
task_context_var: ContextVar[dict[str, str] | None] = ContextVar("task_context", default=None)

# The second argument of each task is the id it works on; the first is the organization id.
TASK_ID_FIELDS = {
    "documents.process_batch": "job_id",
    "cases.compare": "job_id",
    "system.ping": "job_id",
    "investigations.run": "investigation_id",
    "reports.generate": "report_id",
    "doccompare.run": "comparison_id",
    "doccompare.export": "export_id",
}
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def task_context(name: str, celery_id: str | None, args: tuple[Any, ...]) -> dict[str, str]:
    """Log context of a task run. Only well-formed ids are taken from the arguments."""
    ctx = {"task": name}
    if celery_id:
        ctx["task_id"] = celery_id
    if args and isinstance(args[0], str) and _UUID.match(args[0]):
        ctx["organization_id"] = args[0]
    field = TASK_ID_FIELDS.get(name)
    if field and len(args) > 1 and isinstance(args[1], str) and _UUID.match(args[1]):
        ctx[field] = args[1]
    return ctx


# Keys that must never reach a log line, even if passed by mistake.
_REDACTED_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "authorization",
    }
)
_STD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, var in (
            ("request_id", request_id_var),
            ("job_id", job_id_var),
            ("organization_id", org_id_var),
        ):
            value = var.get()
            if value:
                payload[key] = value
        for key, value in (task_context_var.get() or {}).items():
            payload.setdefault(key, value)
        for key, value in record.__dict__.items():
            if key in _STD_ATTRS or key.startswith("_"):
                continue
            payload[key] = "[redacted]" if key.lower() in _REDACTED_KEYS else value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
