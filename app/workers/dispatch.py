"""Hand-off from the API to Celery. Imported lazily so the API never loads worker code."""

from __future__ import annotations

import uuid


def enqueue_processing(organization_id: uuid.UUID, job_id: uuid.UUID) -> None:
    from app.workers.document_tasks import process_batch

    process_batch.delay(str(organization_id), str(job_id))


def enqueue_graph_sync() -> None:
    """Drain the graph outbox now instead of waiting for the next scheduled run."""
    from app.workers.graph_tasks import drain_outbox

    drain_outbox.delay()


def enqueue_comparison(organization_id: uuid.UUID, job_id: uuid.UUID) -> None:
    from app.workers.comparison_tasks import compare_case

    compare_case.delay(str(organization_id), str(job_id))
