"""The report model: one field per section, in the order the requirements list them. It is
built only from persisted rows; every renderer works from it."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# (field, heading) in the required order (reporting requirement 1.1).
SECTIONS: list[tuple[str, str]] = [
    ("executive_summary", "Executive summary"),
    ("scope", "Scope"),
    ("documents_analyzed", "Documents analyzed"),
    ("entities_identified", "Entities identified"),
    ("extracted_information", "Extracted information"),
    ("identified_discrepancies", "Identified discrepancies"),
    ("forensic_observations", "Forensic observations"),
    ("evidence_references", "Evidence references"),
    ("relationship_analysis", "Relationship analysis"),
    ("missing_supporting_documents", "Missing supporting documents"),
    ("alternative_explanations", "Alternative explanations (hypotheses)"),
    ("recommended_human_review", "Recommended human review"),
    ("limitations", "Limitations"),
    ("audit", "Audit information"),
]
NOT_REVIEWED = "Not yet reviewed"


class Citation(BaseModel):
    """An evidence reference: the finding it supports and where the value is printed."""

    finding_id: uuid.UUID | None = None
    document_id: uuid.UUID
    filename: str
    page: int | None
    field_id: uuid.UUID | None = None
    field_name: str
    value: str | None
    role: str | None = None


class Scope(BaseModel):
    case_title: str
    investigation_type: str
    objective: str
    documents: int
    findings: int


class DocumentRow(BaseModel):
    document_id: uuid.UUID
    filename: str
    doc_type: str | None
    pages: int | None
    sha256: str
    status: str


class EntityRow(BaseModel):
    entity_id: uuid.UUID
    type: str
    name: str
    mentions: int
    status: str


class FieldRow(BaseModel):
    field_id: uuid.UUID
    name: str
    value: str | None
    page: int | None
    method: str
    confidence: str | None


class DocumentFields(BaseModel):
    document_id: uuid.UUID
    filename: str
    fields: list[FieldRow]


class Discrepancy(BaseModel):
    finding_id: uuid.UUID
    type: str
    title: str
    severity: str
    priority: str
    anomaly_score: str | None
    evidence_confidence: str | None
    explanation: str
    review_status: str
    review_label: str = Field(description='The human review status; "Not yet reviewed" if new')
    evidence: list[Citation]
    limitations: list[str]


class ForensicObservation(BaseModel):
    document_id: uuid.UUID
    filename: str
    anomaly_id: uuid.UUID
    type: str
    severity: str
    page: int | None
    explanation: str


class RelationshipRow(BaseModel):
    relationship_id: uuid.UUID
    type: str
    source: str
    target: str
    finding_id: uuid.UUID | None
    evidence_count: int


class MissingItem(BaseModel):
    text: str
    source: Literal["comparison_rule", "investigation", "evidence_request"]
    finding_id: uuid.UUID | None = None


class Hypothesis(BaseModel):
    finding_id: uuid.UUID
    text: str
    hypothesis: Literal[True] = True


class ReviewItem(BaseModel):
    text: str
    finding_id: uuid.UUID | None = None


class Audit(BaseModel):
    report_id: uuid.UUID
    generated_at: datetime
    generated_by: str | None
    investigation_id: uuid.UUID | None
    investigation_approved_by: str | None
    investigation_approved_at: datetime | None
    pipeline_versions: list[str]
    summary_method: Literal["investigation_model", "template"]
    summary_note: str | None = None


class ReportModel(BaseModel):
    title: str
    report_id: uuid.UUID
    investigation_id: uuid.UUID | None
    organization: str
    objective: str
    executive_summary: str
    scope: Scope
    documents_analyzed: list[DocumentRow]
    entities_identified: list[EntityRow]
    extracted_information: list[DocumentFields]
    identified_discrepancies: list[Discrepancy]
    forensic_observations: list[ForensicObservation]
    evidence_references: list[Citation]
    relationship_analysis: list[RelationshipRow]
    missing_supporting_documents: list[MissingItem]
    alternative_explanations: list[Hypothesis]
    recommended_human_review: list[ReviewItem]
    limitations: list[str]
    audit: Audit
    label: Literal["SYNTHETIC DEMONSTRATION DATA"] | None = None
