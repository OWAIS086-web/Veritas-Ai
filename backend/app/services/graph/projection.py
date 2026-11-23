"""Build the case graph from documents, extracted fields, entities and findings.

Pure and deterministic. Every edge carries the ids of the extracted fields or evidence items
it is based on, and an edge without evidence is never produced. Ids are UUIDv5 of the case
and the edge's ends, so a rebuild keeps them stable.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.services.comparison.model import DocInfo, FieldObs, doc_label
from app.services.entity_resolution.resolve import ResolvedEntity

NAMESPACE = uuid.UUID("0b8f6a3e-9f1d-4e7a-8a2c-5d3b9e7f1c42")
NODE_KINDS = ("document", "entity", "finding")
EDGE_TYPES = (
    "ISSUED_BY",
    "ISSUED_TO",
    "REFERENCES",
    "BELONGS_TO",
    "PAID_BY",
    "SHIPPED_UNDER",
    "SUPPORTS",
    "CONTRADICTS",
    "DERIVED_FROM",
    "ASSOCIATED_WITH",
)

# How a party named on a document relates to it. Anything else is ASSOCIATED_WITH.
PARTY_EDGES: dict[tuple[str, str], str] = {
    ("purchase_order", "buyer"): "ISSUED_BY",
    ("purchase_order", "supplier"): "ISSUED_TO",
    ("commercial_invoice", "supplier"): "ISSUED_BY",
    ("commercial_invoice", "buyer"): "ISSUED_TO",
    ("packing_list", "supplier"): "ISSUED_BY",
    ("packing_list", "buyer"): "ISSUED_TO",
    ("insurance_certificate", "insurer"): "ISSUED_BY",
    ("insurance_certificate", "buyer"): "ISSUED_TO",
    ("customs_declaration", "buyer"): "ISSUED_BY",
    ("payment_receipt", "buyer"): "PAID_BY",
}
ADDRESS_OF = {"supplier_address": "supplier", "buyer_address": "buyer"}
# reference field -> document type whose own number it cites
DOC_REFERENCES = {
    "invoice_reference": "commercial_invoice",
    "po_reference": "purchase_order",
    "bill_of_lading_reference": "bill_of_lading",
}


@dataclass(frozen=True)
class EvidenceRef:
    id: uuid.UUID
    document_id: uuid.UUID
    role: str
    normalized_value: Any


@dataclass(frozen=True)
class FindingRef:
    id: uuid.UUID
    type: str
    title: str
    severity: str
    status: str
    evidence: tuple[EvidenceRef, ...]


@dataclass
class GraphNode:
    id: uuid.UUID
    kind: str  # document | entity | finding
    type: str
    label: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    id: uuid.UUID
    type: str
    source_kind: str
    source_id: uuid.UUID
    target_kind: str
    target_id: uuid.UUID
    evidence_ids: list[uuid.UUID]
    finding_id: uuid.UUID | None = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class CaseGraph:
    nodes: list[GraphNode]
    edges: list[GraphEdge]


def edge_id(
    case_id: uuid.UUID, type_: str, src: uuid.UUID, tgt: uuid.UUID, extra: str = ""
) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{case_id}:{type_}:{src}:{tgt}:{extra}")


class _Edges:
    def __init__(self, case_id: uuid.UUID) -> None:
        self.case_id = case_id
        self.by_id: dict[uuid.UUID, GraphEdge] = {}

    def add(
        self,
        type_: str,
        src: tuple[str, uuid.UUID],
        tgt: tuple[str, uuid.UUID],
        evidence: Sequence[uuid.UUID],
        finding_id: uuid.UUID | None = None,
        **properties: Any,
    ) -> None:
        if not evidence:
            return  # never an edge without evidence
        eid = edge_id(self.case_id, type_, src[1], tgt[1], str(finding_id or ""))
        edge = self.by_id.get(eid)
        if edge is None:
            self.by_id[eid] = GraphEdge(
                eid,
                type_,
                src[0],
                src[1],
                tgt[0],
                tgt[1],
                sorted(set(evidence), key=str),
                finding_id,
                dict(properties),
            )
            return
        edge.evidence_ids = sorted(set(edge.evidence_ids) | set(evidence), key=str)
        for key, value in properties.items():
            if key in edge.properties and edge.properties[key] != value:
                edge.properties[key] = sorted({*_as_list(edge.properties[key]), *_as_list(value)})
            else:
                edge.properties[key] = value


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else [value]


def _key(obs: FieldObs) -> str:
    return str(obs.normalized.get("key") or "") if isinstance(obs.normalized, dict) else ""


def _value_key(value: Any) -> str:
    if isinstance(value, dict):
        for k in ("amount", "quantity", "date", "key", "name"):
            if k in value:
                return f"{k}:{value[k]}:{value.get('currency') or value.get('unit') or ''}"
    return repr(value)


def document_node(d: DocInfo) -> GraphNode:
    return GraphNode(
        d.id,
        "document",
        d.doc_type or "unknown",
        d.filename,
        {"doc_type_label": doc_label(d.doc_type)},
    )


def entity_node(
    id_: uuid.UUID, type_: str, name: str, status: str, mentions: int, confidence: Any
) -> GraphNode:
    return GraphNode(
        id_,
        "entity",
        type_,
        name,
        {
            "status": status,
            "mention_count": mentions,
            "confidence": None if confidence is None else str(confidence),
        },
    )


def finding_node(f: FindingRef) -> GraphNode:
    # The review status changes outside comparison runs, so it is read from the finding
    # itself, not stored in the graph copy.
    return GraphNode(f.id, "finding", f.type, f.title, {"severity": f.severity})


def project(
    case_id: uuid.UUID,
    docs: Sequence[DocInfo],
    fields: Sequence[FieldObs],
    entities: Sequence[ResolvedEntity],
    findings: Sequence[FindingRef],
) -> CaseGraph:
    completed = {d.id: d for d in docs if d.status == "completed"}
    nodes: dict[uuid.UUID, GraphNode] = {}
    for d in sorted(completed.values(), key=lambda d: (d.filename, str(d.id))):
        nodes[d.id] = document_node(d)
    entity_of: dict[uuid.UUID, ResolvedEntity] = {}
    for e in entities:
        nodes[e.id] = entity_node(
            e.id, e.type, e.canonical_name, e.status, len(e.mentions), e.confidence
        )
        for m in e.mentions:
            entity_of[m.field_id] = e
    edges = _Edges(case_id)

    usable = [f for f in fields if f.usable and f.document_id in completed]
    for f in usable:
        entity = entity_of.get(f.field_id)
        if entity is None or entity.type == "address":
            continue  # addresses attach to their party below, not to the document
        doc = completed[f.document_id]
        if entity.type == "organization":
            type_ = PARTY_EDGES.get((doc.doc_type or "", f.name), "ASSOCIATED_WITH")
        elif entity.type == "shipment":
            type_ = "SHIPPED_UNDER"
        elif entity.type == "transaction":
            type_ = "REFERENCES"
        else:
            type_ = "ASSOCIATED_WITH"
        edges.add(type_, ("document", doc.id), ("entity", entity.id), [f.field_id], role=f.name)

    # An address belongs to the party printed next to it on the same document.
    by_doc: dict[uuid.UUID, dict[str, FieldObs]] = {}
    for f in usable:
        by_doc.setdefault(f.document_id, {})[f.name] = f
    for named in by_doc.values():
        for address_field, party_field in ADDRESS_OF.items():
            address, party = named.get(address_field), named.get(party_field)
            if address is None or party is None:
                continue
            a, p = entity_of.get(address.field_id), entity_of.get(party.field_id)
            if a is not None and p is not None:
                edges.add(
                    "BELONGS_TO", ("entity", a.id), ("entity", p.id),
                    [address.field_id, party.field_id], role=address_field,
                )

    numbers: dict[tuple[str, str], list[FieldObs]] = {}
    for f in usable:
        doc = completed[f.document_id]
        if f.name == "document_number" and doc.doc_type and _key(f):
            numbers.setdefault((doc.doc_type, _key(f)), []).append(f)
    for f in usable:
        target_type = DOC_REFERENCES.get(f.name)
        if target_type is None or not _key(f):
            continue
        for target in numbers.get((target_type, _key(f)), []):
            if target.document_id != f.document_id:
                edges.add(
                    "REFERENCES",
                    ("document", f.document_id),
                    ("document", target.document_id),
                    [f.field_id, target.field_id],
                    role=f.name,
                )

    for finding in findings:
        nodes[finding.id] = finding_node(finding)
        in_case = [e for e in finding.evidence if e.document_id in completed]
        for ev in in_case:
            edges.add("SUPPORTS", ("document", ev.document_id), ("finding", finding.id), [ev.id])
        conflicting = sorted(
            (e for e in in_case if e.role == "conflicting"),
            key=lambda e: (_value_key(e.normalized_value), str(e.document_id)),
        )
        for i, a in enumerate(conflicting):
            for b in conflicting[i + 1 :]:
                if a.document_id == b.document_id:
                    continue
                if _value_key(a.normalized_value) == _value_key(b.normalized_value):
                    continue
                edges.add(
                    "CONTRADICTS",
                    ("document", a.document_id),
                    ("document", b.document_id),
                    [a.id, b.id],
                    finding.id,
                    finding_type=finding.type,
                )

    ordered = sorted(
        edges.by_id.values(), key=lambda e: (e.type, str(e.source_id), str(e.target_id), str(e.id))
    )
    return CaseGraph(list(nodes.values()), ordered)
