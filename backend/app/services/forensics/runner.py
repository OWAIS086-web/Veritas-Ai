"""The `forensics` pipeline stage: gather the inputs, run the analyses off the event loop,
and replace the document's forensic run (separate from extraction)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import tenant_session
from app.integrations.storage.base import ObjectStore
from app.models import (
    Document,
    DocumentStatus,
    DocumentVersion,
    ExtractedField,
    ExtractionRun,
    ForensicAnomaly,
    ForensicRun,
)
from app.services.forensics.analyze import Settings, analyze_document
from app.services.forensics.model import FieldBox
from app.services.forensics.stamps import ANALYSIS as STAMPS

# Field types a forensic region can be related to.
RELEVANT = {"amount", "reference", "quantity", "date", "party"}


def _settings() -> Settings:
    s = get_settings()
    return Settings(
        dpi=s.forensics_dpi,
        max_pages=s.forensics_max_pages,
        noise_k=s.forensics_noise_k,
        version_ssim=s.forensics_version_ssim,
        stamp_threshold=s.forensics_stamp_threshold,
    )


async def _field_boxes(s: Any, org: uuid.UUID, document_id: uuid.UUID) -> list[FieldBox]:
    run_id = await s.scalar(
        select(ExtractionRun.id)
        .where(ExtractionRun.organization_id == org, ExtractionRun.document_id == document_id)
        .order_by(ExtractionRun.started_at.desc())
        .limit(1)
    )
    if run_id is None:
        return []
    rows = await s.scalars(
        select(ExtractedField).where(
            ExtractedField.organization_id == org, ExtractedField.extraction_run_id == run_id
        )
    )
    return [
        FieldBox(str(f.id), f.name, f.value_type, f.page_number, tuple(f.bbox))
        for f in rows
        if f.status == "extracted" and f.bbox and f.page_number and f.value_type in RELEVANT
    ]


async def _other_stamps(s: Any, org: uuid.UUID, doc: Document) -> list[dict[str, Any]]:
    """Stamps found earlier on the other completed documents of the same case."""
    rows = (
        await s.execute(
            select(ForensicRun, Document.original_filename)
            .join(Document, Document.id == ForensicRun.document_id)
            .where(
                ForensicRun.organization_id == org,
                Document.case_id == doc.case_id,
                Document.id != doc.id,
                Document.status == DocumentStatus.COMPLETED,
            )
            .order_by(ForensicRun.started_at.desc())
        )
    ).all()
    seen: set[uuid.UUID] = set()
    out: list[dict[str, Any]] = []
    for run, filename in rows:
        if run.document_id in seen:
            continue  # latest run per document only
        seen.add(run.document_id)
        for region in run.structure.get(STAMPS, {}).get("regions", []):
            if region.get("kind") == "stamp" and region.get("descriptor"):
                out.append({**region, "document_id": str(run.document_id), "filename": filename})
    return out


async def run_document_forensics(
    org: uuid.UUID, doc: Document, store: ObjectStore
) -> dict[str, Any]:
    settings = _settings()
    async with tenant_session(org) as s:
        fields = await _field_boxes(s, org, doc.id)
        previous = await s.scalar(
            select(Document)
            .join(DocumentVersion, DocumentVersion.supersedes_id == Document.id)
            .where(DocumentVersion.organization_id == org, DocumentVersion.document_id == doc.id)
        )
        others = await _other_stamps(s, org, doc)
        previous_ref = (previous.storage_key, previous.mime_type) if previous else None
    data = await store.get(doc.storage_key)
    previous_data = None
    if previous_ref is not None:
        previous_data = (await store.get(previous_ref[0]), previous_ref[1])
    started = datetime.now(UTC)
    report = await asyncio.to_thread(
        analyze_document, data, doc.mime_type, fields, settings, previous_data, others
    )
    async with tenant_session(org) as s:
        await s.execute(
            delete(ForensicRun).where(
                ForensicRun.organization_id == org,
                ForensicRun.document_id == doc.id,
                ForensicRun.pipeline_version == doc.pipeline_version,
            )
        )
        run = ForensicRun(
            id=uuid.uuid4(),
            organization_id=org,
            document_id=doc.id,
            pipeline_version=doc.pipeline_version,
            analysis_types=report.analysis_types,
            pdf_metadata=report.pdf_metadata,
            structure=report.structure,
            limitations=report.limitations,
            status=report.status,
            started_at=started,
            finished_at=datetime.now(UTC),
        )
        s.add(run)
        await s.flush()
        for a in report.anomalies:
            s.add(
                ForensicAnomaly(
                    organization_id=org,
                    forensic_run_id=run.id,
                    document_id=doc.id,
                    type=a.type,
                    page_number=a.page_number,
                    region=a.region,
                    severity=a.severity,
                    explanation=a.explanation,
                    metrics=a.metrics,
                    requires_review=a.requires_review,
                )
            )
    return {
        "status": report.status,
        "analysis_types": report.analysis_types,
        "anomalies": len(report.anomalies),
        "medium": sum(a.severity == "medium" for a in report.anomalies),
        "compared_with_version": previous_ref is not None,
        "stamps_compared": len(others),
    }
