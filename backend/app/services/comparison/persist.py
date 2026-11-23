"""Load a case's extracted fields, run the rules, and upsert findings with their evidence.

Idempotent: findings are keyed by (case_id, rule_id:signature). A re-run refreshes the
detected values, scores and evidence, and never touches the human review status or the
original detector output (`ai_output_json`). A finding the latest run no longer detects is
marked inactive, not deleted, so its decisions stay attached.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.models import (
    Case,
    Document,
    DocumentStatus,
    EvidenceItem,
    ExtractedField,
    ExtractionRun,
    Finding,
    FindingStatus,
)
from app.services.comparison.engine import EngineResult, evaluate_all
from app.services.comparison.model import DocInfo, FieldObs, FindingDraft, RuleContext
from app.services.risk.scoring import evidence_confidence, priority

DETECTOR = "rules"  # Phase 3 findings come from deterministic rules only; no model is called.


async def _lock_case(s: AsyncSession, org: uuid.UUID, case_id: uuid.UUID) -> Case:
    # The row lock serializes concurrent comparisons of one case.
    found = await s.scalar(
        select(Case)
        .where(Case.id == case_id, Case.organization_id == org, Case.deleted_at.is_(None))
        .with_for_update()
    )
    if found is None:
        raise NotFoundError("Case not found.")
    return found


async def load_inputs(
    s: AsyncSession, org: uuid.UUID, case_id: uuid.UUID
) -> tuple[list[DocInfo], list[FieldObs], int]:
    """Documents of the case, the fields of each completed document's latest extraction
    run, and the number of documents still waiting or processing."""
    docs = list(
        await s.scalars(
            select(Document)
            .where(Document.organization_id == org, Document.case_id == case_id)
            .order_by(Document.uploaded_at, Document.id)
        )
    )
    infos = [DocInfo(d.id, d.original_filename, d.doc_type, d.sha256, d.status) for d in docs]
    pending = sum(d.status in (DocumentStatus.UPLOADED, DocumentStatus.PROCESSING) for d in docs)
    completed = {d.id: d for d in docs if d.status == DocumentStatus.COMPLETED}
    if not completed:
        return infos, [], pending
    latest: dict[uuid.UUID, uuid.UUID] = {}
    for run in await s.scalars(
        select(ExtractionRun)
        .where(ExtractionRun.organization_id == org, ExtractionRun.document_id.in_(completed))
        .order_by(ExtractionRun.started_at.desc(), ExtractionRun.id)
    ):
        latest.setdefault(run.document_id, run.id)
    rows = await s.scalars(
        select(ExtractedField).where(
            ExtractedField.organization_id == org,
            ExtractedField.extraction_run_id.in_(list(latest.values())),
        )
    )
    fields = [
        FieldObs(
            field_id=r.id,
            document_id=r.document_id,
            doc_type=completed[r.document_id].doc_type,
            filename=completed[r.document_id].original_filename,
            name=r.name,
            value=r.value,
            normalized=r.normalized_value,
            value_type=r.value_type,
            currency=r.currency,
            role=r.semantic_role,
            confidence=r.confidence,
            page_number=r.page_number,
            bbox=r.bbox,
            location=r.location,
            status=r.status,
            rejection_reason=r.rejection_reason,
        )
        for r in rows
    ]
    fields.sort(key=lambda f: (f.filename, f.name, str(f.field_id)))
    return infos, fields, pending


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


def _evidence_json(draft: FindingDraft) -> list[dict[str, Any]]:
    return [
        {
            "document_id": e.obs.document_id,
            "field_id": e.obs.field_id,
            "field": e.obs.name,
            "page": e.obs.page_number,
            "bbox": e.obs.bbox,
            "location": e.obs.location,
            "value": e.obs.value,
            "role": e.role,
        }
        for e in draft.evidence
    ]


def _scored(draft: FindingDraft) -> dict[str, Any]:
    confidence = evidence_confidence(e.obs.confidence for e in draft.evidence)
    level = priority(draft.severity, confidence, draft.evidence_status)
    return {
        "type": draft.type,
        "title": draft.title[:200],
        "severity": draft.severity,
        "field": draft.field,
        "currency": draft.currency,
        "difference": draft.difference,
        "explanation": draft.explanation,
        "severity_rationale": f"{draft.severity_rationale} Priority: {level.rationale}",
        "limitations": draft.limitations,
        "anomaly_score": draft.anomaly_score,
        "evidence_confidence": confidence,
        "priority": level.level,
        "evidence_status": draft.evidence_status,
        "requires_human_review": draft.severity != "info",
        "recommended_action": draft.recommended_action,
        "coverage": _jsonable(draft.coverage),
        "detected_by": f"{draft.rule_id}@{draft.rule_version}",
    }


def _snapshot(draft: FindingDraft, scored: dict[str, Any], now: datetime) -> dict[str, Any]:
    snapshot: dict[str, Any] = _jsonable(
        {
            "detector": DETECTOR,
            "model": None,
            "rule_id": draft.rule_id,
            "rule_version": draft.rule_version,
            "generated_at": now.isoformat(),
            "output": {**scored, "details": draft.details, "evidence": _evidence_json(draft)},
        }
    )
    return snapshot


async def _refresh_evidence(
    s: AsyncSession, org: uuid.UUID, finding: Finding, draft: FindingDraft
) -> None:
    current = list(
        await s.scalars(select(EvidenceItem).where(EvidenceItem.finding_id == finding.id))
    )
    wanted = {(e.obs.field_id, e.role): e for e in draft.evidence}
    keep = {(row.extracted_field_id, row.role) for row in current} & set(wanted)
    stale = [row.id for row in current if (row.extracted_field_id, row.role) not in keep]
    if stale:
        await s.execute(delete(EvidenceItem).where(EvidenceItem.id.in_(stale)))
    for key, e in wanted.items():
        if key in keep:
            continue
        s.add(
            EvidenceItem(
                organization_id=org,
                finding_id=finding.id,
                document_id=e.obs.document_id,
                extracted_field_id=e.obs.field_id,
                field_name=e.obs.name,
                page_number=e.obs.page_number,
                bbox=e.obs.bbox,
                location=e.obs.location,
                value=e.obs.value,
                normalized_value=e.obs.normalized,
                confidence=e.obs.confidence,
                role=e.role,
            )
        )


async def upsert_findings(
    s: AsyncSession,
    org: uuid.UUID,
    case_id: uuid.UUID,
    result: EngineResult,
    now: datetime,
) -> dict[str, int]:
    existing = {
        f.finding_key: f
        for f in await s.scalars(
            select(Finding).where(Finding.organization_id == org, Finding.case_id == case_id)
        )
    }
    counts = {"created": 0, "updated": 0, "deactivated": 0}
    for draft in result.drafts:
        scored = _scored(draft)
        row = existing.get(draft.key)
        if row is None:
            row = Finding(
                id=uuid.uuid4(),
                organization_id=org,
                case_id=case_id,
                finding_key=draft.key,
                rule_id=draft.rule_id,
                status=FindingStatus.NEW,
                ai_output_json=_snapshot(draft, scored, now),
                active=True,
                last_detected_at=now,
                **scored,
            )
            s.add(row)
            await s.flush()
            counts["created"] += 1
        else:
            for key, value in scored.items():
                setattr(row, key, value)
            row.active = True
            row.last_detected_at = now
            counts["updated"] += 1
        await _refresh_evidence(s, org, row, draft)
    detected = {d.key for d in result.drafts}
    for key, row in existing.items():
        # Findings of a rule that failed this time are left as they were.
        if key not in detected and row.active and row.rule_id not in result.failed:
            row.active = False
            counts["deactivated"] += 1
    await s.flush()
    return counts


async def run_comparison(
    s: AsyncSession, org: uuid.UUID, case_id: uuid.UUID, rules: Sequence[Any] | None = None
) -> dict[str, Any]:
    """Compare every completed document of one case and persist the findings."""
    settings = get_settings()
    case = await _lock_case(s, org, case_id)
    docs, fields, pending = await load_inputs(s, org, case_id)
    ctx = RuleContext(
        investigation_type=case.investigation_type,
        amount_tolerance=settings.amount_tolerance,
        name_threshold=settings.name_similarity_threshold,
        pending_documents=pending,
    )
    now = datetime.now(UTC)
    result = (
        evaluate_all(fields, docs, ctx) if rules is None else evaluate_all(fields, docs, ctx, rules)
    )
    counts = await upsert_findings(s, org, case_id, result, now)
    case.compared_at = now
    active = sum(1 for _ in result.drafts)
    return {
        "case_id": str(case_id),
        "documents_compared": sum(d.status == DocumentStatus.COMPLETED for d in docs),
        "documents_pending": pending,
        "findings": active,
        **counts,
        "rules_ran": result.ran,
        "rules_failed": result.failed,
    }
