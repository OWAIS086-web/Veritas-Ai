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


def enqueue_investigation(organization_id: uuid.UUID, investigation_id: uuid.UUID) -> None:
    from app.workers.investigation_tasks import run

    run.delay(str(organization_id), str(investigation_id))


def enqueue_report(organization_id: uuid.UUID, report_id: uuid.UUID) -> None:
    from app.workers.report_tasks import generate_report

    generate_report.delay(str(organization_id), str(report_id))


def enqueue_comparison(organization_id: uuid.UUID, job_id: uuid.UUID) -> None:
    from app.workers.comparison_tasks import compare_case

    compare_case.delay(str(organization_id), str(job_id))


def enqueue_document_comparison(organization_id: uuid.UUID, comparison_id: uuid.UUID) -> None:
    from app.workers.doccompare_tasks import run

    run.delay(str(organization_id), str(comparison_id))


def enqueue_comparison_export(organization_id: uuid.UUID, export_id: uuid.UUID) -> None:
    from app.workers.doccompare_tasks import export

    export.delay(str(organization_id), str(export_id))
