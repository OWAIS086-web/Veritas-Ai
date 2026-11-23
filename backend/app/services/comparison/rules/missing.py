"""Expected documents that are absent from an international shipment case."""

from __future__ import annotations

from collections.abc import Sequence

from app.services.comparison.model import (
    DocInfo,
    FieldObs,
    FindingDraft,
    RuleContext,
    RuleSpec,
    doc_label,
)

RULE_ID = "missing.expected_documents"
VERSION = "1.0"
EXPECTED: dict[str, tuple[str, ...]] = {
    "international_shipment": (
        "purchase_order",
        "commercial_invoice",
        "packing_list",
        "bill_of_lading",
        "customs_declaration",
        "payment_receipt",
    ),
}


def evaluate(
    fields: Sequence[FieldObs], docs: Sequence[DocInfo], ctx: RuleContext
) -> list[FindingDraft]:
    expected = EXPECTED.get(ctx.investigation_type)
    completed = [d for d in docs if d.status == "completed"]
    # Until every document has finished processing, a type can't be called missing.
    if not expected or not completed or ctx.pending_documents:
        return []
    present = {d.doc_type for d in completed}
    failed = [d for d in docs if d.status == "failed"]
    unclassified = [d for d in completed if d.doc_type in (None, "unknown")]
    limitations = []
    if failed:
        limitations.append(
            f"{len(failed)} document(s) failed processing, so their type is unknown and one of "
            "them may be the missing document: " + ", ".join(sorted(d.filename for d in failed))
        )
    if unclassified:
        limitations.append(
            f"{len(unclassified)} document(s) could not be classified: "
            + ", ".join(sorted(d.filename for d in unclassified))
        )
    expected_text = ", ".join(doc_label(t).lower() for t in expected)
    drafts = []
    for doc_type in expected:
        if doc_type in present:
            continue
        label = doc_label(doc_type)
        drafts.append(
            FindingDraft(
                rule_id=RULE_ID,
                rule_version=VERSION,
                signature=doc_type,
                type="missing_document",
                title=f"No {label.lower()} in the case",
                severity="medium",
                severity_rationale=(
                    "Medium: the values this document would confirm cannot be cross-checked."
                ),
                explanation=(
                    f"None of the {len(completed)} processed documents was classified as a "
                    f"{label.lower()}. For an international shipment case the expected "
                    f"documents are: {expected_text}."
                ),
                recommended_action=f"Request the {label.lower()} from the parties involved.",
                evidence=[],
                limitations=limitations,
                details={"expected": list(expected), "present": sorted(t or "" for t in present)},
            )
        )
    return drafts


RULES = (RuleSpec(RULE_ID, VERSION, evaluate),)
