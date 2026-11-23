"""References that should match across documents (shipment, PO, invoice, bill of lading).

A document's own number (for example the invoice's `document_number`) is compared with the
references other documents make to it (`invoice_reference`). Keys are normalized at
extraction (no spaces, dashes or slashes; upper case).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from decimal import Decimal

from app.services.comparison.model import (
    DocInfo,
    EvidenceDraft,
    FieldObs,
    FindingDraft,
    RuleContext,
    RuleSpec,
    cite,
    coverage_for,
)

RULE_ID = "references.match"
VERSION = "1.0"

# reference -> (document type or None for any, field name)
GROUPS: dict[str, tuple[tuple[str | None, str], ...]] = {
    "shipment_reference": ((None, "shipment_reference"),),
    "invoice_reference": (("commercial_invoice", "document_number"), (None, "invoice_reference")),
    "po_reference": (("purchase_order", "document_number"), (None, "po_reference")),
    "bill_of_lading_reference": (
        ("bill_of_lading", "document_number"),
        (None, "bill_of_lading_reference"),
    ),
}
LABELS = {
    "shipment_reference": "shipment reference",
    "invoice_reference": "invoice number",
    "po_reference": "purchase order number",
    "bill_of_lading_reference": "bill of lading number",
}


def key_of(obs: FieldObs) -> str:
    return str(obs.normalized.get("key") or "")


def _members(fields: Sequence[FieldObs], group: str) -> list[FieldObs]:
    out = []
    for f in fields:
        if not f.usable or not key_of(f):
            continue
        for doc_type, name in GROUPS[group]:
            if f.name == name and (doc_type is None or f.doc_type == doc_type):
                out.append(f)
                break
    return out


def evaluate(
    fields: Sequence[FieldObs], docs: Sequence[DocInfo], ctx: RuleContext
) -> list[FindingDraft]:
    drafts = []
    for group, label in LABELS.items():
        members = _members(fields, group)
        counts = Counter(key_of(f) for f in members)
        if len({f.document_id for f in members}) < 2 or len(counts) < 2:
            continue
        top = max(counts.values())
        outside = len(members) - top
        ordered = sorted(members, key=lambda f: (key_of(f), f.filename))
        drafts.append(
            FindingDraft(
                rule_id=RULE_ID,
                rule_version=VERSION,
                signature=group,
                type="conflicting_reference",
                title=f"Documents cite different {label}s",
                severity="medium",
                severity_rationale=(
                    "Medium: references that should identify the same transaction disagree, "
                    "which needs review but is not a monetary difference by itself."
                ),
                explanation="; ".join(f'{cite(f)} states "{f.value}"' for f in ordered) + ".",
                recommended_action=(
                    f"Confirm which {label} the documents belong to, and whether any document "
                    "relates to a different transaction."
                ),
                evidence=[EvidenceDraft(f, "conflicting") for f in ordered],
                field=group,
                anomaly_score=(Decimal(outside) / Decimal(len(members))).quantize(Decimal("0.001")),
                limitations=[
                    "A case can legitimately contain more than one shipment, order or invoice. "
                    "References are compared after removing spaces, dashes and slashes."
                ],
                coverage={
                    "field": group,
                    "compared_documents": sorted({str(f.document_id) for f in members}),
                    "skipped": coverage_for(GROUPS[group][-1][1], fields, docs)["skipped"],
                },
            )
        )
    return drafts


RULES = (RuleSpec(RULE_ID, VERSION, evaluate),)
