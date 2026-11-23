"""Builds the `ReportModel` from persisted rows only: the case, its documents and extracted
fields, findings and their evidence, forensic runs, entities and relationships, evidence
requests and (optionally) an approved investigation. Nothing is computed that a row doesn't
state, except counts and the template summary built from them."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.models import (
    Document,
    DocumentPage,
    Entity,
    EvidenceRequest,
    Investigation,
    InvestigationStatus,
    Organization,
    User,
)
from app.models.forensics import MANDATORY_LIMITATION
from app.services.cases.service import get_case
from app.services.documents import service as documents
from app.services.findings import service as findings
from app.services.forensics import queries as forensics
from app.services.graph import queries as graph
from app.services.reporting import model as m
from app.services.reporting.verify import unverified_tokens

SYNTHETIC_MARK = "SYNTHETIC DEMONSTRATION DATA"
FINDING_STATUS_LABELS = {
    "new": m.NOT_REVIEWED,
    "under_review": "Under review",
    "confirmed_observation": "Confirmed observation",
    "needs_more_evidence": "Needs more evidence",
    "dismissed": "Dismissed",
    "resolved": "Resolved",
}
REPORT_LIMITATIONS = [
    "This report states observations from the documents provided. It does not establish that "
    "any document is authentic or forged, or that any person or organization acted unlawfully.",
    "Findings come from deterministic comparison rules over extracted values; a value that "
    "could not be verified on its page was left out, not guessed.",
]


def _dec(value: Any) -> str | None:
    return None if value is None else str(value)


async def _email(s: AsyncSession, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    email: str | None = await s.scalar(select(User.email).where(User.id == user_id))
    return email


async def _investigation(
    s: AsyncSession, org: uuid.UUID, case_id: uuid.UUID, investigation_id: uuid.UUID | None
) -> Investigation | None:
    if investigation_id is None:
        return None
    inv = await s.scalar(
        select(Investigation).where(
            Investigation.id == investigation_id,
            Investigation.organization_id == org,
            Investigation.case_id == case_id,
        )
    )
    if inv is None:
        raise NotFoundError("Investigation not found.")
    # Reporting requirement 3.2: reports from investigations only after human approval.
    if inv.status != InvestigationStatus.COMPLETED or inv.approved_at is None:
        raise ConflictError(
            "A report can use an investigation only after it was approved and completed."
        )
    return inv


async def _synthetic(s: AsyncSession, org: uuid.UUID, case_id: uuid.UUID) -> bool:
    """True when a page of the case is printed with the synthetic-data label (product rule 13)."""
    hit = await s.scalar(
        select(DocumentPage.id)
        .join(Document, Document.id == DocumentPage.document_id)
        .where(
            DocumentPage.organization_id == org,
            Document.case_id == case_id,
            DocumentPage.text.contains(SYNTHETIC_MARK),
        )
        .limit(1)
    )
    return hit is not None


def template_summary(model: m.ReportModel) -> str:
    """A factual summary from the counts and titles in the model (no model call)."""
    f = model.identified_discrepancies
    high = sum(1 for x in f if x.severity == "high")
    unreviewed = sum(1 for x in f if x.review_status == "new")
    text = (
        f'The case "{model.scope.case_title}" contains {model.scope.documents} document(s). '
        f"Comparison of their extracted values produced {model.scope.findings} finding(s), "
        f"{high} of high severity; {unreviewed} have not yet been reviewed by a person."
    )
    if f:
        text += f" The highest-ranked finding is: {f[0].title}."
    if model.forensic_observations:
        count = len(model.forensic_observations)
        text += f" Forensic analysis recorded {count} observation(s) for review."
    return text


async def build_report(
    s: AsyncSession,
    org: uuid.UUID,
    case_id: uuid.UUID,
    report_id: uuid.UUID,
    investigation_id: uuid.UUID | None,
    created_by: uuid.UUID | None,
) -> m.ReportModel:
    case = await get_case(s, org, case_id)
    inv = await _investigation(s, org, case_id, investigation_id)
    org_name = await s.scalar(select(Organization.name).where(Organization.id == org)) or ""

    docs = await documents.list_for_case(s, org, case_id)
    extracted: list[m.DocumentFields] = []
    for d in docs:
        run = await documents.extractions(s, org, d.id)
        fields = [
            m.FieldRow(
                field_id=f.id,
                name=f.name,
                value=f.value,
                page=f.page_number,
                method=f.method,
                confidence=_dec(f.confidence),
            )
            for f in (run.fields if run else [])
            if f.status == "extracted"
        ]
        extracted.append(
            m.DocumentFields(document_id=d.id, filename=d.original_filename, fields=fields)
        )

    summaries = await findings.list_for_case(s, org, case_id, False)
    discrepancies: list[m.Discrepancy] = []
    citations: list[m.Citation] = []
    missing: list[m.MissingItem] = []
    for f in summaries:
        detail = await findings.get(s, org, f.id)
        ev = [
            m.Citation(
                finding_id=f.id,
                document_id=e.document_id,
                filename=e.document_filename,
                page=e.page_number,
                field_id=e.extracted_field_id,
                field_name=e.field_name,
                value=e.value,
                role=e.role,
            )
            for e in detail.evidence
        ]
        citations += ev
        if f.evidence_status == "absence":
            missing.append(m.MissingItem(text=f.title, source="comparison_rule", finding_id=f.id))
        discrepancies.append(
            m.Discrepancy(
                finding_id=f.id,
                type=f.type,
                title=f.title,
                severity=f.severity,
                priority=f.priority,
                anomaly_score=_dec(f.anomaly_score),
                evidence_confidence=_dec(f.evidence_confidence),
                explanation=detail.explanation,
                review_status=f.status,
                review_label=FINDING_STATUS_LABELS.get(f.status, f.status),
                evidence=ev,
                limitations=list(detail.limitations),
            )
        )

    observations: list[m.ForensicObservation] = []
    forensic_limits: list[str] = []
    for row in await forensics.case_summary(s, org, case_id):
        frun = await forensics.latest_run(s, org, row.document_id)
        if frun is None:
            continue
        forensic_limits += [x for x in frun.limitations if x not in forensic_limits]
        observations += [
            m.ForensicObservation(
                document_id=row.document_id,
                filename=row.filename,
                anomaly_id=a.id,
                type=a.type,
                severity=a.severity,
                page=a.page_number,
                explanation=a.explanation,
            )
            for a in frun.anomalies
        ]

    entities = [
        m.EntityRow(
            entity_id=e.id,
            type=e.type,
            name=e.canonical_name,
            mentions=e.mention_count,
            status=e.status,
        )
        for e in await s.scalars(
            select(Entity)
            .where(Entity.organization_id == org, Entity.case_id == case_id)
            .order_by(Entity.type, Entity.canonical_name)
        )
    ]
    g = await graph.case_graph(s, None, org, case_id, None, None)
    labels = {n.id: n.label for n in g.nodes}
    relationships = [
        m.RelationshipRow(
            relationship_id=e.id,
            type=e.type,
            source=labels.get(e.source, str(e.source)),
            target=labels.get(e.target, str(e.target)),
            finding_id=e.finding_id,
            evidence_count=len(e.evidence_ids),
        )
        for e in g.edges
    ]

    for req in await s.scalars(
        select(EvidenceRequest)
        .where(EvidenceRequest.organization_id == org, EvidenceRequest.case_id == case_id)
        .order_by(EvidenceRequest.created_at)
    ):
        missing.append(
            m.MissingItem(
                text=f"Requested by a reviewer: {', '.join(req.document_types)}. {req.note}",
                source="evidence_request",
                finding_id=req.finding_id,
            )
        )

    finding_ids = {d.finding_id for d in discrepancies}
    hypotheses: list[m.Hypothesis] = []
    review: list[m.ReviewItem] = [
        m.ReviewItem(text=f"Review: {d.title}", finding_id=d.finding_id)
        for d in discrepancies
        if d.review_status in ("new", "under_review", "needs_more_evidence")
    ]
    investigation_summary: str | None = None
    if inv is not None:
        agents = inv.result.get("agents", {})
        for item in agents.get("cross_reference", {}).get("missing_information", []):
            if item.get("source") == "model":
                missing.append(m.MissingItem(text=item["text"], source="investigation"))
        for a in agents.get("risk", {}).get("assessments", []):
            fid = uuid.UUID(a["finding_id"])
            if fid in finding_ids:
                hypotheses += [
                    m.Hypothesis(finding_id=fid, text=h["text"])
                    for h in a.get("alternative_explanations", [])
                ]
        draft = inv.result.get("report_draft") or {}
        for item in draft.get("sections", []):
            if item.get("key") != "recommended_review":
                continue
            for rec in item.get("items", []):
                cited = [r for r in rec.get("refs", []) if r.get("finding_id")]
                rec_finding = uuid.UUID(cited[0]["finding_id"]) if cited else None
                if rec_finding is None or rec_finding in finding_ids:
                    review.append(m.ReviewItem(text=rec["text"], finding_id=rec_finding))
        if draft.get("summary_status") == "verified":
            investigation_summary = draft.get("executive_summary")

    limitations = list(REPORT_LIMITATIONS)
    for disc in discrepancies:
        limitations += [x for x in disc.limitations if x not in limitations]
    if observations or forensic_limits:
        limitations += [x for x in [MANDATORY_LIMITATION, *forensic_limits] if x not in limitations]

    generated_by = await _email(s, created_by)
    model = m.ReportModel(
        title=f"Investigation report: {case.title}",
        report_id=report_id,
        investigation_id=inv.id if inv else None,
        organization=org_name,
        objective=(inv.objective if inv else case.objective) or "",
        executive_summary="",
        scope=m.Scope(
            case_title=case.title,
            investigation_type=case.investigation_type,
            objective=case.objective or "",
            documents=len(docs),
            findings=len(discrepancies),
        ),
        documents_analyzed=[
            m.DocumentRow(
                document_id=d.id,
                filename=d.original_filename,
                doc_type=d.doc_type,
                pages=d.page_count,
                sha256=d.sha256,
                status=d.status,
            )
            for d in docs
        ],
        entities_identified=entities,
        extracted_information=extracted,
        identified_discrepancies=discrepancies,
        forensic_observations=observations,
        evidence_references=citations,
        relationship_analysis=relationships,
        missing_supporting_documents=missing,
        alternative_explanations=hypotheses,
        recommended_human_review=review,
        limitations=limitations,
        audit=m.Audit(
            report_id=report_id,
            generated_at=datetime.now(UTC),
            generated_by=generated_by,
            investigation_id=inv.id if inv else None,
            investigation_approved_by=await _email(s, inv.approved_by) if inv else None,
            investigation_approved_at=inv.approved_at if inv else None,
            pipeline_versions=sorted({d.pipeline_version for d in docs}),
            summary_method="template",
        ),
        label="SYNTHETIC DEMONSTRATION DATA" if await _synthetic(s, org, case_id) else None,
    )
    model.executive_summary = template_summary(model)
    if investigation_summary:
        # The investigation's model-written summary is re-checked against this report's
        # content (requirement 1.3); if it names anything the content doesn't, the
        # template summary stays.
        bad = unverified_tokens(
            investigation_summary, model.model_dump(mode="json", exclude={"executive_summary"})
        )
        if bad:
            model.audit.summary_note = (
                f"Investigation summary not used: unsupported values {', '.join(bad[:5])}."
            )
        else:
            model.executive_summary = investigation_summary
            model.audit.summary_method = "investigation_model"
    return model
