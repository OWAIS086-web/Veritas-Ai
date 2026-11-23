"""Worker side of a comparison: wait for both documents to finish processing, run the engine,
persist the findings, and generate the exports.

Idempotent: a completed or failed comparison is left as it is; a re-run after a crash replaces
the comparison's own findings. Stage and progress are persisted so the UI shows real status.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import tenant_session
from app.core.logging import get_logger
from app.integrations.llm.openai_compat import configured_vision_provider, vision_status
from app.integrations.storage.base import ObjectStore, derived_key
from app.models import (
    COMPARISON_LIMITATION,
    ComparisonExport,
    ComparisonFinding,
    Document,
    DocumentComparison,
    DocumentStatus,
)
from app.services.audit import service as audit
from app.services.doccompare import annotate, report
from app.services.doccompare.engine import DocInput, EngineResult, EngineSettings
from app.services.doccompare.engine import run as run_engine
from app.services.doccompare.fusion import Candidate
from app.services.doccompare.service import EXPORT_MIME, findings, get_comparison
from app.services.doccompare.vision import Vision, VisionStats
from app.services.documents import service as documents

logger = get_logger(__name__)
VisionFactory = Callable[[], Awaitable[tuple[Vision | None, str, str | None]]]
AUTO_EXPORTS = ("annotated_pdf", "annotated_images", "report_pdf", "findings_json")


async def default_vision() -> tuple[Vision | None, str, str | None]:
    """The configured vision model if it is enabled and reachable: (vision, status, note)."""
    s = get_settings()
    if not s.comparison_vlm_enabled:
        return None, "disabled", "VERITAS_COMPARISON_VLM_ENABLED is false"
    provider = configured_vision_provider()
    if provider is None:
        return None, "unavailable", "VERITAS_LLM_BASE_URL or VERITAS_VLM_MODEL is not set"
    status = await vision_status()
    if not (status["reachable"] and status["model_available"]):
        return None, "unavailable", status.get("error")
    return (
        Vision(provider, s.vlm_model, VisionStats(status="not_run", model=s.vlm_model)),
        "used",
        None,
    )


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=float))


async def _set(org: uuid.UUID, cid: uuid.UUID, **values: Any) -> None:
    async with tenant_session(org) as s:
        c = await get_comparison(s, org, cid)
        for k, v in values.items():
            setattr(c, k, v)


async def fail_comparison(org: uuid.UUID, cid: uuid.UUID, error: str) -> str:
    async with tenant_session(org) as s:
        c = await get_comparison(s, org, cid)
        c.status, c.error, c.finished_at = "failed", error[:2000], datetime.now(UTC)
        await audit.record(
            s,
            "comparison.failed",
            organization_id=org,
            actor_user_id=c.created_by,
            resource_type="document_comparison",
            resource_id=cid,
            metadata={"error": error[:300]},
        )
    return "failed"


async def _input(s: Any, org: uuid.UUID, doc: Document, store: ObjectStore) -> DocInput:
    pages = [p.model_dump(mode="json") for p in await documents.pages(s, org, doc.id)]
    ext = await documents.extractions(s, org, doc.id)
    fields = [
        f.model_dump(mode="json")
        for f in (ext.fields if ext else [])
        if f.status == "extracted" and f.bbox and f.page_number
    ]
    data = await store.get(doc.storage_key)
    if hashlib.sha256(data).hexdigest() != doc.sha256:
        raise ValueError(f"{doc.original_filename}: the stored file doesn't match its SHA-256")
    return DocInput(
        str(doc.id), doc.original_filename, data, doc.mime_type, doc.sha256, pages, fields
    )


def _finding_row(org: uuid.UUID, cid: uuid.UUID, n: int, c: Candidate) -> ComparisonFinding:
    return ComparisonFinding(
        organization_id=org,
        comparison_id=cid,
        number=n,
        type=c.type,
        sources=c.sources,
        test_page=c.test_page,
        original_page=c.original_page,
        region=c.region,
        original_region=c.original_region,
        original_text=c.original_text,
        test_text=c.test_text,
        severity=c.severity,
        evidence_confidence=Decimal(str(c.confidence)),
        explanation=c.explanation,
        metrics=_jsonable(
            {
                **c.metrics,
                "method": c.method,
                "digits_changed": c.digits_changed,
                "confidence_basis": c.basis,
                "extracted_fields": c.fields,
            }
        ),
        vlm_assessment=_jsonable(c.vlm) if c.vlm else None,
        review_status="unreviewed",
    )


async def run_comparison(
    org: uuid.UUID, cid: uuid.UUID, store: ObjectStore, vision_factory: VisionFactory | None = None
) -> str:
    """Returns completed | failed | waiting (both documents aren't processed yet) | missing."""
    async with tenant_session(org) as s:
        c = await s.scalar(
            select(DocumentComparison)
            .where(DocumentComparison.id == cid, DocumentComparison.organization_id == org)
            .with_for_update()
        )
        if c is None:
            return "missing"
        if c.status in ("completed", "failed"):
            return c.status
        docs = {
            d.id: d
            for d in await s.scalars(
                select(Document).where(
                    Document.organization_id == org,
                    Document.id.in_([c.original_document_id, c.test_document_id]),
                )
            )
        }
        original, test = docs.get(c.original_document_id), docs.get(c.test_document_id)
        problem: str | None = None
        if original is None or test is None:
            problem = "A compared document no longer exists."
        elif failed := [
            d.original_filename for d in (original, test) if d.status == DocumentStatus.FAILED
        ]:
            problem = f"Document processing failed for {', '.join(failed)}."
        elif not all(d.status == DocumentStatus.COMPLETED for d in (original, test)):
            c.status, c.stage, c.progress = "waiting_for_documents", "waiting_for_documents", 5
            return "waiting"
        else:
            c.status, c.stage, c.progress = "running", "loading_documents", 10
            c.started_at = datetime.now(UTC)
        cfg_raw = c.settings or {}
    # The row lock is released before the failure is written in a transaction of its own.
    if problem is not None or original is None or test is None:
        return await fail_comparison(org, cid, problem or "A compared document no longer exists.")
    try:
        async with tenant_session(org) as s:
            o_in = await _input(s, org, original, store)
            t_in = await _input(s, org, test, store)
    except Exception as exc:
        return await fail_comparison(org, cid, f"The documents could not be loaded: {exc}"[:400])
    s_now = get_settings()
    cfg = EngineSettings(
        dpi=int(cfg_raw.get("dpi", s_now.comparison_dpi)),
        max_pages=int(cfg_raw.get("max_pages", s_now.comparison_max_pages)),
        work_width=int(cfg_raw.get("work_width", s_now.comparison_work_width)),
        ssim_threshold=float(cfg_raw.get("ssim_threshold", s_now.comparison_ssim_threshold)),
        vlm_max_regions=int(cfg_raw.get("vlm_max_regions", s_now.comparison_vlm_max_regions)),
        vlm_max_pages=int(cfg_raw.get("vlm_max_pages", s_now.comparison_vlm_max_pages)),
    )

    async def progress(stage: str, pct: int) -> None:
        await _set(org, cid, stage=stage, progress=pct)

    try:
        vision, vlm_status, vlm_note = await (vision_factory or default_vision)()
        result: EngineResult = await run_engine(o_in, t_in, cfg, vision, progress)
    except Exception as exc:
        logger.warning(
            "comparison_failed", extra={"comparison": str(cid), "error": type(exc).__name__}
        )
        return await fail_comparison(
            org, cid, f"The comparison could not run: {type(exc).__name__}: {str(exc)[:300]}"
        )
    if vision is not None:
        vlm_status = vision.stats.status if vision.stats.status != "not_run" else "used"
    summary = {
        **result.summary,
        "vlm_status": vlm_status,
        "vlm_note": vlm_note,
        "vlm_provider": "openai_compatible" if vision is not None else None,
    }
    async with tenant_session(org) as s:
        c = await get_comparison(s, org, cid, lock=True)
        await s.execute(
            delete(ComparisonFinding).where(
                ComparisonFinding.organization_id == org, ComparisonFinding.comparison_id == cid
            )
        )
        for n, cand in enumerate(result.findings, start=1):
            s.add(_finding_row(org, cid, n, cand))
        c.summary = _jsonable(summary)
        c.vlm_status = vlm_status
        c.vlm_model = vision.model if vision is not None else None
        c.status, c.stage, c.progress, c.finished_at = (
            "completed",
            "completed",
            100,
            datetime.now(UTC),
        )
        for kind in AUTO_EXPORTS:
            s.add(
                ComparisonExport(
                    organization_id=org,
                    comparison_id=cid,
                    kind=kind,
                    status="queued",
                    created_by=c.created_by,
                )
            )
        await audit.record(
            s,
            "comparison.completed",
            organization_id=org,
            actor_user_id=c.created_by,
            resource_type="document_comparison",
            resource_id=cid,
            metadata={
                "findings": len(result.findings),
                "by_severity": summary.get("by_severity"),
                "vlm_status": vlm_status,
            },
        )
    return "completed"


async def queued_exports(org: uuid.UUID, cid: uuid.UUID) -> list[uuid.UUID]:
    async with tenant_session(org) as s:
        return list(
            await s.scalars(
                select(ComparisonExport.id).where(
                    ComparisonExport.organization_id == org,
                    ComparisonExport.comparison_id == cid,
                    ComparisonExport.status == "queued",
                )
            )
        )


async def payload(s: Any, org: uuid.UUID, c: DocumentComparison) -> dict[str, Any]:
    """The persisted comparison as one dict; every export is rendered from it."""
    rows = await findings(s, org, c.id)
    summary = c.summary or {}
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "comparison": {
            "id": str(c.id),
            "case_id": str(c.case_id),
            "status": c.status,
            "created_at": c.created_at.isoformat(),
            "finished_at": c.finished_at.isoformat() if c.finished_at else None,
            "vlm_status": c.vlm_status,
            "vlm_model": c.vlm_model,
            "settings": c.settings,
        },
        "original": summary.get("original"),
        "test": summary.get("test"),
        "summary": summary,
        "findings": [
            {
                "id": str(f.id),
                "number": f.number,
                "type": f.type,
                "sources": list(f.sources),
                "severity": f.severity,
                "evidence_confidence": float(f.evidence_confidence),
                "confidence_basis": (f.metrics or {}).get("confidence_basis", []),
                "test_page": f.test_page,
                "region": f.region,
                "original_page": f.original_page,
                "original_region": f.original_region,
                "original_text": f.original_text,
                "test_text": f.test_text,
                "explanation": f.explanation,
                "extracted_fields": (f.metrics or {}).get("extracted_fields", []),
                "metrics": f.metrics,
                "vlm_assessment": f.vlm_assessment,
                "review_status": f.review_status,
                "reviewed_at": f.reviewed_at.isoformat() if f.reviewed_at else None,
            }
            for f in rows
        ],
        "limitations": summary.get("limitations") or [COMPARISON_LIMITATION],
    }


def _build(
    kind: str,
    data: dict[str, Any],
    original: tuple[bytes, str],
    test: tuple[bytes, str],
    dpi: int,
    max_pages: int,
) -> bytes:
    if kind == "findings_json":
        return report.findings_json(data)
    if kind == "report_pdf":
        return report.report_pdf(data, original, test, dpi, max_pages)
    # Dismissed differences aren't drawn on the annotated copies (they stay in the JSON).
    marks = [
        annotate.Mark(f["number"], f["test_page"], f["region"], f["severity"], f["explanation"])
        for f in data["findings"]
        if f["region"] and f["test_page"] and f["review_status"] != "dismissed"
    ]
    if kind == "annotated_pdf":
        out, _ = annotate.annotated_pdf(
            test[0], test[1], marks, report.findings_list_pdf(data), dpi, max_pages
        )
        return out
    notes = "\n".join(
        ["VERITAS AI - annotated test document pages.", ""]
        + [f"#{f['number']} [{f['severity']}] {f['explanation']}" for f in data["findings"]]
        + ["", *data["limitations"]]
    )
    out, _ = annotate.annotated_images(test[0], test[1], marks, notes, dpi, max_pages)
    return out


async def generate_export(org: uuid.UUID, export_id: uuid.UUID, store: ObjectStore) -> str:
    async with tenant_session(org) as s:
        e = await s.scalar(
            select(ComparisonExport)
            .where(ComparisonExport.id == export_id, ComparisonExport.organization_id == org)
            .with_for_update()
        )
        if e is None:
            return "missing"
        if e.status != "queued":
            return e.status
        c = await get_comparison(s, org, e.comparison_id)
        data = await payload(s, org, c)
        kind, cid = e.kind, c.id
        o_doc = await documents.get_document(s, org, c.original_document_id)
        t_doc = await documents.get_document(s, org, c.test_document_id)
        dpi = int((c.settings or {}).get("dpi", get_settings().comparison_dpi))
        max_pages = int((c.settings or {}).get("max_pages", get_settings().comparison_max_pages))
        refs = ((o_doc.storage_key, o_doc.mime_type), (t_doc.storage_key, t_doc.mime_type))
    try:
        original = (await store.get(refs[0][0]), refs[0][1])
        test = (await store.get(refs[1][0]), refs[1][1])
        built = await asyncio.to_thread(_build, kind, data, original, test, dpi, max_pages)
        digest = hashlib.sha256(built).hexdigest()
        mime, ext = EXPORT_MIME[kind]
        key = derived_key(org, cid, f"{kind.replace('_', '-')}-{uuid.uuid4().hex[:12]}.{ext}")
        await store.put_derived(key, built, mime)
    except Exception as exc:
        logger.warning(
            "comparison_export_failed",
            extra={"export": str(export_id), "error": type(exc).__name__},
        )
        async with tenant_session(org) as s:
            e = await s.get_one(ComparisonExport, export_id)
            e.status, e.error, e.finished_at = (
                "failed",
                f"{type(exc).__name__}: {str(exc)[:300]}",
                datetime.now(UTC),
            )
        return "failed"
    async with tenant_session(org) as s:
        e = await s.get_one(ComparisonExport, export_id)
        e.status, e.storage_key, e.sha256, e.size_bytes = "completed", key, digest, len(built)
        e.finished_at = datetime.now(UTC)
        await audit.record(
            s,
            "comparison.export_generated",
            organization_id=org,
            actor_user_id=e.created_by,
            resource_type="comparison_export",
            resource_id=export_id,
            metadata={"kind": kind, "sha256": digest, "comparison_id": str(cid)},
        )
    return "completed"
