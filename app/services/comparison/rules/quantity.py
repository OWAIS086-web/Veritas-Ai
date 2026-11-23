"""Total quantity across documents (packing list, bill of lading, invoice, ...).

Quantities are compared only when they are stated in the same unit.
"""

from __future__ import annotations

from collections import defaultdict
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
from app.services.risk.scoring import relative_difference, severity_for_relative

FIELD = "total_quantity"
RULE_ID = "quantity.total_quantity"
VERSION = "1.0"


def quantity_of(obs: FieldObs) -> Decimal:
    return Decimal(str(obs.normalized["quantity"]))


def unit_of(obs: FieldObs) -> str:
    return str(obs.normalized.get("unit") or "")


def evaluate(
    fields: Sequence[FieldObs], docs: Sequence[DocInfo], ctx: RuleContext
) -> list[FindingDraft]:
    groups: dict[str, list[FieldObs]] = defaultdict(list)
    for f in fields:
        if f.name == FIELD and f.usable:
            groups[unit_of(f)].append(f)
    drafts = []
    for unit, group in sorted(groups.items()):
        values = {quantity_of(f) for f in group}
        if len({f.document_id for f in group}) < 2 or len(values) < 2:
            continue
        high, low = max(values), min(values)
        rel = relative_difference(values)
        ordered = sorted(group, key=lambda f: (quantity_of(f), f.filename))
        unit_text = f" {unit}" if unit else ""
        drafts.append(
            FindingDraft(
                rule_id=RULE_ID,
                rule_version=VERSION,
                signature=f"{FIELD}:{unit or 'none'}",
                type="quantity_mismatch",
                title=f"Total quantity differs by {high - low:,}{unit_text}",
                severity=severity_for_relative(rel),
                severity_rationale=(
                    f"The difference is {rel:.1%} of the highest quantity. Thresholds: 10% "
                    "or more is high, 2% or more is medium, otherwise low."
                ),
                explanation="; ".join(
                    f"{cite(f)} states {quantity_of(f):,}{unit_text}" for f in ordered
                )
                + ".",
                recommended_action=(
                    "Check the cited quantities against the packing details and, where "
                    "available, an inspection or tally report."
                ),
                evidence=[EvidenceDraft(f, "conflicting") for f in ordered],
                field=FIELD,
                anomaly_score=rel,
                limitations=[
                    "Partial shipments or split bills of lading can legitimately show "
                    "different quantities."
                ],
                coverage=coverage_for(FIELD, fields, docs),
            )
        )
    return drafts


RULES = (RuleSpec(RULE_ID, VERSION, evaluate),)
