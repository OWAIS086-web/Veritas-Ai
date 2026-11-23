"""Compact, typed tool results. They carry only persisted values and their ids, so every
statement an agent makes can be traced back to a row."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from app.schemas.documents import FieldOut
from app.schemas.findings import FindingDetail, FindingSummary
from app.schemas.forensics import ForensicRunOut, ForensicSummaryOut
from app.schemas.graph import EntityOut, GraphOut, RelationshipOut

MAX_GRAPH_EDGES = 80


class DocumentRow(BaseModel):
    document_id: uuid.UUID
    filename: str
    doc_type: str | None
    status: str
    page_count: int | None


class Documents(BaseModel):
    documents: list[DocumentRow]


class FindingRow(BaseModel):
    finding_id: uuid.UUID
    type: str
    title: str
    severity: str
    priority: str
    anomaly_score: Decimal | None
    evidence_confidence: Decimal | None
    field: str | None
    currency: str | None
    difference: Decimal | None
    status: str
    evidence_status: str
    evidence_count: int

    @classmethod
    def from_summary(cls, f: FindingSummary) -> FindingRow:
        return cls(
            finding_id=f.id,
            type=f.type,
            title=f.title,
            severity=f.severity,
            priority=f.priority,
            anomaly_score=f.anomaly_score,
            evidence_confidence=f.evidence_confidence,
            field=f.field,
            currency=f.currency,
            difference=f.difference,
            status=f.status,
            evidence_status=f.evidence_status,
            evidence_count=f.evidence_count,
        )


class Findings(BaseModel):
    findings: list[FindingRow]


class EvidenceRow(BaseModel):
    evidence_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    doc_type: str | None
    field_id: uuid.UUID | None
    field_name: str
    page: int | None
    value: str | None
    role: str
    confidence: Decimal | None


class FindingEvidence(BaseModel):
    finding_id: uuid.UUID
    type: str
    title: str
    explanation: str
    limitations: list[str]
    evidence: list[EvidenceRow]

    @classmethod
    def from_detail(cls, d: FindingDetail) -> FindingEvidence:
        return cls(
            finding_id=d.id,
            type=d.type,
            title=d.title,
            explanation=d.explanation,
            limitations=list(d.limitations),
            evidence=[
                EvidenceRow(
                    evidence_id=e.id,
                    document_id=e.document_id,
                    filename=e.document_filename,
                    doc_type=e.doc_type,
                    field_id=e.extracted_field_id,
                    field_name=e.field_name,
                    page=e.page_number,
                    value=e.value,
                    role=e.role,
                    confidence=e.confidence,
                )
                for e in d.evidence
            ],
        )


class FieldRow(BaseModel):
    field_id: uuid.UUID
    name: str
    value: str | None
    page: int | None
    status: str
    method: str
    confidence: Decimal | None

    @classmethod
    def from_field(cls, f: FieldOut) -> FieldRow:
        return cls(
            field_id=f.id,
            name=f.name,
            value=f.value,
            page=f.page_number,
            status=f.status,
            method=f.method,
            confidence=f.confidence,
        )


class DocumentFields(BaseModel):
    document_id: uuid.UUID
    filename: str
    doc_type: str | None
    fields: list[FieldRow]


class PageText(BaseModel):
    document_id: uuid.UUID
    page: int
    method: str
    text: str
    truncated: bool


class ForensicDocRow(BaseModel):
    document_id: uuid.UUID
    filename: str
    status: str | None
    anomalies: int
    medium: int
    types: list[str]

    @classmethod
    def from_summary(cls, x: ForensicSummaryOut) -> ForensicDocRow:
        return cls(
            document_id=x.document_id,
            filename=x.filename,
            status=x.status,
            anomalies=x.anomalies,
            medium=x.medium,
            types=list(x.types),
        )


class ForensicAnomalyRow(BaseModel):
    anomaly_id: uuid.UUID
    type: str
    page: int | None
    severity: str
    explanation: str


class ForensicResults(BaseModel):
    """Either the case summary (`documents`) or one document's latest run."""

    documents: list[ForensicDocRow] | None = None
    document_id: uuid.UUID | None = None
    status: str | None = None
    anomalies: list[ForensicAnomalyRow] | None = None
    limitations: list[str] | None = None


class ForensicSummary(ForensicResults):
    pass


class ForensicDocument(ForensicResults):
    @classmethod
    def from_run(cls, document_id: uuid.UUID, run: ForensicRunOut | None) -> ForensicDocument:
        if run is None:
            return cls(document_id=document_id, status=None, anomalies=[], limitations=[])
        return cls(
            document_id=document_id,
            status=run.status,
            anomalies=[
                ForensicAnomalyRow(
                    anomaly_id=a.id,
                    type=a.type,
                    page=a.page_number,
                    severity=a.severity,
                    explanation=a.explanation,
                )
                for a in run.anomalies
            ],
            limitations=list(run.limitations),
        )


class EntityRow(BaseModel):
    entity_id: uuid.UUID
    type: str
    name: str
    status: str | None
    mention_count: int


class Entities(BaseModel):
    entities: list[EntityRow]


class MentionRow(BaseModel):
    document_id: uuid.UUID
    filename: str
    field_id: uuid.UUID
    field_name: str
    value: str | None
    page: int | None


class EntityMentions(BaseModel):
    entity_id: uuid.UUID
    type: str
    name: str
    status: str
    mentions: list[MentionRow]

    @classmethod
    def from_entity(cls, e: EntityOut) -> EntityMentions:
        return cls(
            entity_id=e.id,
            type=e.type,
            name=e.canonical_name,
            status=e.status,
            mentions=[
                MentionRow(
                    document_id=m.document_id,
                    filename=m.document_filename,
                    field_id=m.extracted_field_id,
                    field_name=m.field_name,
                    value=m.value,
                    page=m.page_number,
                )
                for m in e.mentions
            ],
        )


class NodeRow(BaseModel):
    id: uuid.UUID
    kind: str
    type: str
    label: str


class EdgeRow(BaseModel):
    relationship_id: uuid.UUID
    type: str
    source: uuid.UUID
    target: uuid.UUID
    evidence_count: int
    finding_id: uuid.UUID | None


class CaseGraph(BaseModel):
    nodes: list[NodeRow]
    edges: list[EdgeRow]
    total_edges: int

    @classmethod
    def from_graph(cls, g: GraphOut) -> CaseGraph:
        return cls(
            nodes=[NodeRow(id=n.id, kind=n.kind, type=n.type, label=n.label) for n in g.nodes],
            edges=[
                EdgeRow(
                    relationship_id=e.id,
                    type=e.type,
                    source=e.source,
                    target=e.target,
                    evidence_count=len(e.evidence_ids),
                    finding_id=e.finding_id,
                )
                for e in g.edges[:MAX_GRAPH_EDGES]
            ],
            total_edges=g.total_edges,
        )


class RelationshipRow(BaseModel):
    relationship_id: uuid.UUID
    type: str
    source_label: str
    target_label: str
    evidence_count: int
    finding_id: uuid.UUID | None

    @classmethod
    def from_out(cls, x: RelationshipOut) -> RelationshipRow:
        return cls(
            relationship_id=x.id,
            type=x.type,
            source_label=x.source_label,
            target_label=x.target_label,
            evidence_count=len(x.evidence_ids),
            finding_id=x.finding_id,
        )


class Relationships(BaseModel):
    relationships: list[RelationshipRow]


class DraftSaved(BaseModel):
    saved: bool
    sections: int


def brief(payload: dict[str, Any]) -> dict[str, Any]:
    """A short description of a tool result for the event log: list sizes, scalar values."""
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, list):
            out[key] = f"{len(value)} item(s)"
        elif isinstance(value, str):
            out[key] = value if len(value) <= 120 else f"{len(value)} characters"
        elif value is None or isinstance(value, int | float | bool):
            out[key] = value
    return out
