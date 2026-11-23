"""Verifiers run on the report model just before export.

- Citations (requirement 2.2): every finding, document, page, field, entity, relationship and
  anomaly the report names is re-resolved for the same organization and case. Any orphan
  fails the export with the list of bad references.
- Summary (requirement 1.3): a number or id in the executive summary that doesn't appear in
  the structured content is rejected.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.references import Ref, validate_refs
from app.agents.report import unverified_tokens as _unverified_tokens
from app.services.reporting.model import ReportModel


class ReportVerificationError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems[:20]))
        self.problems = problems


def unverified_tokens(summary: str, content: dict[str, Any]) -> list[str]:
    """Numbers and ids in `summary` that `content` doesn't contain."""
    return _unverified_tokens(summary, content)


def references(model: ReportModel) -> list[Ref]:
    refs: list[Ref] = []
    refs += [Ref(document_id=d.document_id) for d in model.documents_analyzed]
    for doc in model.extracted_information:
        refs += [
            Ref(document_id=doc.document_id, page=f.page, field_id=f.field_id) for f in doc.fields
        ]
    for d in model.identified_discrepancies:
        refs.append(Ref(finding_id=d.finding_id))
    refs += [
        Ref(finding_id=c.finding_id, document_id=c.document_id, page=c.page, field_id=c.field_id)
        for c in model.evidence_references
    ]
    refs += [
        Ref(document_id=o.document_id, anomaly_id=o.anomaly_id) for o in model.forensic_observations
    ]
    refs += [Ref(entity_id=e.entity_id) for e in model.entities_identified]
    refs += [
        Ref(relationship_id=r.relationship_id, finding_id=r.finding_id)
        for r in model.relationship_analysis
    ]
    refs += [Ref(finding_id=h.finding_id) for h in model.alternative_explanations]
    refs += [Ref(finding_id=x.finding_id) for x in model.recommended_human_review if x.finding_id]
    refs += [
        Ref(finding_id=y.finding_id) for y in model.missing_supporting_documents if y.finding_id
    ]
    return refs


async def verify_report(
    s: AsyncSession, org: uuid.UUID, case_id: uuid.UUID, model: ReportModel
) -> None:
    """Raise ReportVerificationError listing every reference or summary value that fails."""
    unique = {r.model_dump_json(exclude_none=True): r for r in references(model)}
    _, rejected = await validate_refs(s, org, case_id, list(unique.values()))
    problems = [f"{x.reason}: {x.ref.model_dump_json(exclude_none=True)}" for x in rejected]
    content = model.model_dump(mode="json", exclude={"executive_summary"})
    problems += [
        f"summary_value_not_in_content: {t}"
        for t in unverified_tokens(model.executive_summary, content)
    ]
    if problems:
        raise ReportVerificationError(problems)
