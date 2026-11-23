"""Plain data passed into and out of comparison rules. Rules are pure functions over these."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from dataclasses import field as dc_field
from decimal import Decimal
from typing import Any

from app.services.extraction.fields import FIELDS


@dataclass(frozen=True)
class DocInfo:
    id: uuid.UUID
    filename: str
    doc_type: str | None
    sha256: str
    status: str


@dataclass(frozen=True)
class FieldObs:
    """One persisted extracted_fields row, with the document it belongs to."""

    field_id: uuid.UUID
    document_id: uuid.UUID
    doc_type: str | None
    filename: str
    name: str
    value: str | None
    normalized: Any
    value_type: str
    currency: str | None
    role: str | None
    confidence: Decimal | None
    page_number: int | None
    bbox: list[float] | None
    location: str | None
    status: str
    rejection_reason: str | None = None

    @property
    def usable(self) -> bool:
        return self.status == "extracted" and self.normalized is not None

    @property
    def where(self) -> str:
        if self.page_number is not None:
            return f"page {self.page_number}"
        return self.location or "unknown location"


@dataclass(frozen=True)
class EvidenceDraft:
    obs: FieldObs
    role: str  # supporting | conflicting | context


@dataclass
class FindingDraft:
    rule_id: str
    rule_version: str
    signature: str  # stable within a case: finding_key = f"{rule_id}:{signature}"
    type: str
    title: str
    severity: str  # info | low | medium | high
    severity_rationale: str
    explanation: str
    recommended_action: str
    evidence: list[EvidenceDraft]
    field: str | None = None
    currency: str | None = None
    difference: Decimal | None = None
    anomaly_score: Decimal | None = None
    limitations: list[str] = dc_field(default_factory=list)
    coverage: dict[str, Any] = dc_field(default_factory=dict)
    details: dict[str, Any] = dc_field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.rule_id}:{self.signature}"

    @property
    def evidence_status(self) -> str:
        return "supported" if self.evidence else "absence"


@dataclass(frozen=True)
class RuleContext:
    investigation_type: str
    amount_tolerance: Decimal
    name_threshold: float
    pending_documents: int = 0


EvaluateFn = Callable[[Sequence[FieldObs], Sequence[DocInfo], RuleContext], list[FindingDraft]]


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str
    version: str
    evaluate: EvaluateFn


DOC_LABELS = {
    "purchase_order": "Purchase order",
    "commercial_invoice": "Commercial invoice",
    "packing_list": "Packing list",
    "bill_of_lading": "Bill of lading",
    "customs_declaration": "Customs declaration",
    "insurance_certificate": "Insurance certificate",
    "payment_receipt": "Payment receipt",
    "certificate_of_origin": "Certificate of origin",
    "supplier_agreement": "Supplier agreement",
    "inspection_certificate": "Inspection certificate",
}


def doc_label(doc_type: str | None) -> str:
    return DOC_LABELS.get(doc_type or "", "Unclassified document")


def cite(obs: FieldObs) -> str:
    """Human-readable source of one observation, e.g. 'Customs declaration (03.pdf, page 2)'."""
    return f"{doc_label(obs.doc_type)} ({obs.filename}, {obs.where})"


def money(value: Decimal) -> str:
    return f"{value:,.2f}"


def types_with(name: str) -> tuple[str, ...]:
    """Document types whose extraction catalogue requires this field."""
    return tuple(
        doc_type
        for doc_type, specs in FIELDS.items()
        if any(s.name == name and s.required for s in specs)
    )


def coverage_for(
    name: str,
    fields: Sequence[FieldObs],
    docs: Sequence[DocInfo],
    expected_types: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Which documents were compared for a field, and which expected ones were skipped (and
    why). A skipped document is one whose type normally carries the field but whose value
    was not usable."""
    expected_types = types_with(name) if expected_types is None else expected_types
    usable = {f.document_id for f in fields if f.name == name and f.usable}
    reasons = {
        f.document_id: f.rejection_reason or f.status
        for f in fields
        if f.name == name and not f.usable
    }
    skipped = [
        {"document_id": str(d.id), "filename": d.filename, "reason": reasons.get(d.id, "absent")}
        for d in docs
        if d.doc_type in expected_types and d.id not in usable
    ]
    return {
        "field": name,
        "compared_documents": sorted(str(d) for d in usable),
        "skipped": skipped,
    }
