"""Document processing pipeline: parse -> classify -> extract -> validate.

Each stage is idempotent on (document_id, stage, pipeline_version): a succeeded stage is
skipped, and a re-run replaces only that stage's own rows inside one transaction. Heavy work
(OCR, layout) runs outside any database transaction. Stage state is persisted in
document_stages, so a page reload or a worker restart never loses progress.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import cv2
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import tenant_session
from app.core.logging import get_logger
from app.integrations.llm.base import ProviderError
from app.integrations.llm.openai_compat import configured_provider
from app.integrations.storage.base import ObjectStore, derived_key
from app.models import (
    Document,
    DocumentPage,
    DocumentStage,
    DocumentStatus,
    ExtractedField,
    ExtractionRun,
)
from app.services.classification.rules import classify
from app.services.comparison.persist import run_comparison
from app.services.documents.service import page_image_name
from app.services.extraction import llm as llm_extract
from app.services.extraction import rules as rules_extract
from app.services.extraction.merge import merge_llm_with_rules
from app.services.extraction.result import ExtractedValue
from app.services.extraction.validation import validate_values
from app.services.graph.service import drop_document_edges, rebuild_case_graph
from app.services.jobs.runner import Emitter
from app.services.ocr.service import decode_image
from app.services.parsing.dispatch import ParseError, parse_document
from app.services.parsing.model import Line, ParsedPage

STAGES = ("parse", "classify", "extract", "validate")
logger = get_logger(__name__)
StageFn = Callable[[uuid.UUID, Document], Awaitable[dict[str, Any]]]


class StageError(Exception):
    """A stage failure that retrying won't fix (bad input), so it fails immediately."""


def _now() -> datetime:
    return datetime.now(UTC)


async def _load_document(org: uuid.UUID, document_id: uuid.UUID) -> Document | None:
    async with tenant_session(org) as s:
        return await s.scalar(
            select(Document).where(Document.id == document_id, Document.organization_id == org)
        )


async def _get(s: AsyncSession, document_id: uuid.UUID) -> Document:
    doc = await s.get(Document, document_id)
    if doc is None:
        raise StageError("document_missing")
    return doc


async def _stage_row(s: AsyncSession, doc: Document, stage: str) -> DocumentStage:
    row = await s.scalar(
        select(DocumentStage)
        .where(
            DocumentStage.document_id == doc.id,
            DocumentStage.stage == stage,
            DocumentStage.pipeline_version == doc.pipeline_version,
        )
        .with_for_update()
    )
    if row is None:
        row = DocumentStage(
            organization_id=doc.organization_id,
            document_id=doc.id,
            stage=stage,
            pipeline_version=doc.pipeline_version,
            status="pending",
            attempts=0,
            metrics={},
        )
        s.add(row)
        await s.flush()
    return row


async def _pages(s: AsyncSession, document_id: uuid.UUID) -> list[ParsedPage]:
    rows = await s.scalars(
        select(DocumentPage)
        .where(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_number)
    )
    return [
        ParsedPage(
            page_number=r.page_number,
            width=r.width,
            height=r.height,
            coord_unit=r.coord_unit,
            method=r.method,
            lines=[Line.from_json(ln) for ln in r.lines],
            tables=r.tables,
        )
        for r in rows
    ]


# --- stages ------------------------------------------------------------------------------


def make_stages(store: ObjectStore) -> dict[str, StageFn]:
    async def parse(org: uuid.UUID, doc: Document) -> dict[str, Any]:
        data = await store.get(doc.storage_key)
        try:
            result = await asyncio.to_thread(parse_document, data, doc.mime_type)
        except ParseError as exc:
            raise StageError(exc.reason) from exc
        if doc.mime_type == "image/tiff":
            # Browsers can't display TIFF: keep one PNG per frame as a derived artifact
            # (separate keys; the original is never modified).
            pngs = await asyncio.to_thread(_tiff_pages_as_png, data)
            for number, png in enumerate(pngs, start=1):
                await store.put_derived(
                    derived_key(org, doc.id, page_image_name(number)), png, "image/png"
                )
            result.metrics["page_images"] = len(pngs)
        async with tenant_session(org) as s:
            await s.execute(delete(DocumentPage).where(DocumentPage.document_id == doc.id))
            for page in result.pages:
                s.add(
                    DocumentPage(
                        organization_id=org,
                        document_id=doc.id,
                        page_number=page.page_number,
                        width=page.width,
                        height=page.height,
                        coord_unit=page.coord_unit,
                        method=page.method,
                        text=page.text,
                        lines=[ln.to_json() for ln in page.lines],
                        tables=page.tables,
                        ocr_mean_confidence=(
                            Decimal(str(page.mean_confidence))
                            if page.method == "ocr" and page.mean_confidence
                            else None
                        ),
                    )
                )
            current = await _get(s, doc.id)
            current.page_count = len(result.pages)
            current.language = result.language
        return {**result.metrics, "ocr_engine": result.ocr_version}

    async def classify_stage(org: uuid.UUID, doc: Document) -> dict[str, Any]:
        async with tenant_session(org) as s:
            pages = await _pages(s, doc.id)
            if not pages:
                raise StageError("no_pages")
            result = classify([ln.text for ln in pages[0].lines], "\n".join(p.text for p in pages))
            current = await _get(s, doc.id)
            current.doc_type = result.doc_type
            current.classification_confidence = (
                Decimal(str(result.score)) if result.score is not None else None
            )
        return {
            "doc_type": result.doc_type,
            "score": result.score,
            "method": result.method,
            "evidence": result.evidence,
        }

    async def extract(org: uuid.UUID, doc: Document) -> dict[str, Any]:
        async with tenant_session(org) as s:
            pages = await _pages(s, doc.id)
            parse_row = await _stage_row(s, doc, "parse")
            ocr_version = parse_row.metrics.get("ocr_engine")
            current = await _get(s, doc.id)
            doc_type = current.doc_type or "unknown"
        start = time.perf_counter()
        notes: dict[str, Any] = {"doc_type": doc_type}
        method, provider_name, model_version, prompt_version = (
            "rules",
            None,
            rules_extract.RULES_VERSION,
            None,
        )
        values: list[ExtractedValue]
        rules_values = rules_extract.extract(doc_type, pages, ocr_version)
        provider = configured_provider()
        if provider is not None and doc_type != "unknown":
            try:
                llm_values, llm_notes = await llm_extract.extract(provider, doc_type, pages)
                notes["llm"] = llm_notes
                method, provider_name = "llm", llm_notes.get("provider")
                model_version = str(llm_notes.get("model"))
                prompt_version = llm_extract.PROMPT_VERSION
                values, merge_notes = merge_llm_with_rules(llm_values, rules_values)
                notes.update(merge_notes)
            except ProviderError as exc:
                notes["llm_failed"] = str(exc)[:300]
                values = rules_values
        else:
            notes["llm"] = "not configured" if provider is None else "skipped: unknown type"
            values = rules_values
        values = validate_values(values)
        notes["extract_ms"] = round((time.perf_counter() - start) * 1000, 1)
        async with tenant_session(org) as s:
            await drop_document_edges(s, org, doc.id)
            await s.execute(
                delete(ExtractionRun).where(
                    ExtractionRun.document_id == doc.id,
                    ExtractionRun.pipeline_version == doc.pipeline_version,
                )
            )
            run = ExtractionRun(
                id=uuid.uuid4(),
                organization_id=org,
                document_id=doc.id,
                pipeline_version=doc.pipeline_version,
                method=method,
                provider=provider_name,
                model_version=model_version,
                prompt_version=prompt_version,
                status="succeeded",
                notes=notes,
                started_at=_now(),
                finished_at=_now(),
            )
            s.add(run)
            await s.flush()
            for v in values:
                s.add(
                    ExtractedField(
                        organization_id=org,
                        extraction_run_id=run.id,
                        document_id=doc.id,
                        name=v.name,
                        value=v.value,
                        normalized_value=v.normalized,
                        value_type=v.value_type,
                        currency=v.currency,
                        semantic_role=v.semantic_role,
                        confidence=(
                            Decimal(str(round(v.confidence, 3)))
                            if v.confidence is not None
                            else None
                        ),
                        page_number=v.page_number,
                        bbox=[round(c, 2) for c in v.bbox] if v.bbox else None,
                        location=v.location,
                        method=v.method,
                        model_version=v.model_version,
                        status=v.status,
                        rejection_reason=v.rejection_reason,
                    )
                )
        extracted = sum(v.status == "extracted" for v in values)
        return {
            "method": method,
            "fields": len(values),
            "extracted": extracted,
            "uncertain": len(values) - extracted,
            "extract_ms": notes["extract_ms"],
        }

    async def validate(org: uuid.UUID, doc: Document) -> dict[str, Any]:
        """Document-level check of what was persisted: every extracted field must have a
        value, a page (or location) and a well-formed normalized value."""
        async with tenant_session(org) as s:
            rows = list(
                await s.scalars(select(ExtractedField).where(ExtractedField.document_id == doc.id))
            )
        problems = [
            r.name
            for r in rows
            if r.status == "extracted"
            and (
                r.value is None
                or r.normalized_value is None
                or (r.page_number is None and r.location is None)
            )
        ]
        if problems:
            raise StageError(f"invalid_persisted_fields:{','.join(problems)}")
        return {"fields": len(rows), "uncertain": [r.name for r in rows if r.status != "extracted"]}

    return {"parse": parse, "classify": classify_stage, "extract": extract, "validate": validate}


# --- orchestration -------------------------------------------------------------------------


async def _mark(org: uuid.UUID, doc: Document, stage: str, **changes: Any) -> DocumentStage:
    async with tenant_session(org) as s:
        row = await _stage_row(s, doc, stage)
        for key, value in changes.items():
            setattr(row, key, value)
        current = await s.get(Document, doc.id)
        if current is not None:
            current.current_stage = stage
        return row


async def process_document(
    org: uuid.UUID,
    document_id: uuid.UUID,
    store: ObjectStore,
    emit: Emitter | None = None,
    stages: dict[str, StageFn] | None = None,
) -> str:
    """Run every pending stage of one document. Returns the final document status."""
    settings = get_settings()
    doc = await _load_document(org, document_id)
    if doc is None:
        return "missing"
    stage_fns = stages or make_stages(store)

    async def say(event: str, data: dict[str, Any]) -> None:
        if emit is not None:
            await emit(
                event, {"document_id": str(doc.id), "filename": doc.original_filename, **data}
            )

    async with tenant_session(org) as s:
        current = await _get(s, doc.id)
        current.status = DocumentStatus.PROCESSING
        current.error = None

    for stage in STAGES:
        async with tenant_session(org) as s:
            row = await _stage_row(s, doc, stage)
            if row.status == "succeeded":
                continue
        await say("stage_started", {"stage": stage})
        error: str | None = None
        for attempt in range(1, settings.stage_max_attempts + 1):
            started = _now()
            row = await _mark(
                org,
                doc,
                stage,
                status="running",
                started_at=started,
                attempts=(row.attempts or 0) + 1,
                error=None,
            )
            t0 = time.perf_counter()
            try:
                metrics = await stage_fns[stage](org, doc)
            except StageError as exc:
                error, retryable = str(exc), False
            except Exception as exc:
                logger.warning(
                    "stage_failed",
                    extra={"stage": stage, "document": str(doc.id), "error": type(exc).__name__},
                )
                error, retryable = f"{type(exc).__name__}: {exc}"[:1000], True
            else:
                metrics["duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                await _mark(
                    org, doc, stage, status="succeeded", finished_at=_now(), metrics=metrics
                )
                await say("stage_completed", {"stage": stage, "metrics": _brief(metrics)})
                error = None
                break
            await _mark(org, doc, stage, status="failed", finished_at=_now(), error=error)
            if not retryable or attempt == settings.stage_max_attempts:
                break
            await say("stage_retry", {"stage": stage, "attempt": attempt, "error": error[:300]})
            await asyncio.sleep(min(8.0, 0.5 * 2**attempt))
        if error is not None:
            async with tenant_session(org) as s:
                current = await _get(s, doc.id)
                current.status = DocumentStatus.FAILED
                current.error = f"{stage}: {error}"[:2000]
            await say("document_failed", {"stage": stage, "error": error[:300]})
            return DocumentStatus.FAILED.value

    async with tenant_session(org) as s:
        current = await _get(s, doc.id)
        current.status = DocumentStatus.COMPLETED
        current.current_stage = None
        current.processed_at = _now()
        doc_type = current.doc_type
    await say("document_completed", {"doc_type": doc_type})
    return DocumentStatus.COMPLETED.value


def _tiff_pages_as_png(data: bytes) -> list[bytes]:
    out = []
    for rgb in decode_image(data):
        ok, png = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        if not ok:
            raise StageError("could_not_render_tiff_page")
        out.append(png.tobytes())
    return out


def _brief(metrics: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "duration_ms",
        "pages",
        "methods",
        "doc_type",
        "score",
        "fields",
        "extracted",
        "uncertain",
        "method",
    )
    return {k: metrics[k] for k in keep if k in metrics}


async def process_batch(
    org: uuid.UUID, payload: dict[str, Any], emit: Emitter, store: ObjectStore
) -> dict[str, Any]:
    ids = [uuid.UUID(i) for i in payload.get("document_ids", [])]
    outcome: dict[str, list[str]] = {"completed": [], "failed": [], "missing": []}
    for index, document_id in enumerate(ids):
        status = await process_document(org, document_id, store, emit)
        outcome.setdefault(status, []).append(str(document_id))
        await emit(
            "progress",
            {"done": index + 1, "total": len(ids)},
            progress=int((index + 1) / max(1, len(ids)) * 100),
        )
    comparisons = await _compare_cases(org, ids, emit)
    return {
        "documents": len(ids),
        **{k: len(v) for k, v in outcome.items()},
        "failed_ids": outcome["failed"],
        "comparisons": comparisons,
    }


async def _compare_cases(
    org: uuid.UUID, document_ids: list[uuid.UUID], emit: Emitter
) -> list[dict[str, Any]]:
    """Re-compare every case touched by this batch. A comparison failure is reported on the
    job but does not undo the processed documents; it can be re-run from the API."""
    if not document_ids:
        return []
    async with tenant_session(org) as s:
        case_ids = sorted(
            set(
                await s.scalars(
                    select(Document.case_id).where(
                        Document.organization_id == org, Document.id.in_(document_ids)
                    )
                )
            )
        )
    summaries = []
    for case_id in case_ids:
        await emit("comparison_started", {"case_id": str(case_id)})
        try:
            async with tenant_session(org) as s:
                summary = await run_comparison(s, org, case_id)
                # Same transaction: the graph rows and their outbox row commit with the
                # findings they are derived from.
                summary["graph"] = await rebuild_case_graph(s, org, case_id)
        except Exception as exc:
            logger.warning(
                "comparison_failed", extra={"case": str(case_id), "error": type(exc).__name__}
            )
            await emit("comparison_failed", {"case_id": str(case_id), "error": type(exc).__name__})
            continue
        await emit(
            "comparison_completed",
            {k: summary[k] for k in ("case_id", "findings", "created", "rules_failed")},
        )
        summaries.append(summary)
    return summaries
