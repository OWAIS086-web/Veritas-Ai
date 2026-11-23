"""Dates: same-role dates that differ, and business ordering checks (informational).

Only dates with the same semantic role are compared with each other. An order date and a
shipment date are never treated as conflicting values.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date

from app.services.comparison.model import (
    DocInfo,
    EvidenceDraft,
    FieldObs,
    FindingDraft,
    RuleContext,
    RuleSpec,
    cite,
)
from app.services.risk.scoring import bounded

SAME_ROLE_ID = "dates.same_role"
ORDER_ID = "dates.order"
VERSION = "1.0"

# (later role, earlier role, signature, statement). The later event is expected on or after
# the earlier one.
ORDERING = (
    (
        "payment_date",
        "invoice_date",
        "payment_before_invoice",
        "payment is dated before the invoice",
    ),
    ("shipment_date", "order_date", "shipment_before_order", "shipment is dated before the order"),
)


def date_of(obs: FieldObs) -> date:
    return date.fromisoformat(str(obs.normalized["date"]))


def role_of(obs: FieldObs) -> str | None:
    return obs.role or (obs.normalized.get("role") if isinstance(obs.normalized, dict) else None)


def _dates(fields: Sequence[FieldObs]) -> dict[str, list[FieldObs]]:
    by_role: dict[str, list[FieldObs]] = defaultdict(list)
    for f in fields:
        if f.value_type == "date" and f.usable and (role := role_of(f)):
            by_role[role].append(f)
    return dict(by_role)


def evaluate_same_role(
    fields: Sequence[FieldObs], docs: Sequence[DocInfo], ctx: RuleContext
) -> list[FindingDraft]:
    drafts = []
    for role, group in sorted(_dates(fields).items()):
        values = {date_of(f) for f in group}
        if len({f.document_id for f in group}) < 2 or len(values) < 2:
            continue
        span = (max(values) - min(values)).days
        ordered = sorted(group, key=lambda f: (date_of(f), f.filename))
        label = role.replace("_", " ")
        drafts.append(
            FindingDraft(
                rule_id=SAME_ROLE_ID,
                rule_version=VERSION,
                signature=role,
                type="date_inconsistency",
                title=f"Documents state different {label}s ({span} days apart)",
                severity="medium",
                severity_rationale="Medium: the same event is dated differently.",
                explanation="; ".join(f"{cite(f)} states {date_of(f).isoformat()}" for f in ordered)
                + ".",
                recommended_action=f"Confirm the correct {label} with the issuing parties.",
                evidence=[EvidenceDraft(f, "conflicting") for f in ordered],
                field=role,
                anomaly_score=bounded(min(span, 30) / 30),
                limitations=["Amended documents can legitimately restate a date."],
                details={"span_days": span},
            )
        )
    return drafts


def evaluate_order(
    fields: Sequence[FieldObs], docs: Sequence[DocInfo], ctx: RuleContext
) -> list[FindingDraft]:
    by_role = _dates(fields)
    drafts = []
    for later_role, earlier_role, signature, statement in ORDERING:
        later, earlier = by_role.get(later_role, []), by_role.get(earlier_role, [])
        pairs = [(a, b) for a in later for b in earlier if date_of(a) < date_of(b)]
        if not pairs:
            continue
        unique = {f.field_id: f for pair in pairs for f in pair}
        involved = sorted(unique.values(), key=lambda f: (f.filename, f.name))
        drafts.append(
            FindingDraft(
                rule_id=ORDER_ID,
                rule_version=VERSION,
                signature=signature,
                type="date_inconsistency",
                title=f"The {statement}",
                severity="info",
                severity_rationale=(
                    "Informational: the order is unusual but can be legitimate (for example "
                    "advance payment or a pro-forma invoice)."
                ),
                explanation="; ".join(
                    f"{cite(a)} states {date_of(a).isoformat()}, which is before "
                    f"{date_of(b).isoformat()} on {cite(b)}"
                    for a, b in pairs
                )
                + ".",
                recommended_action="Check the payment and shipping terms that apply.",
                evidence=[EvidenceDraft(f, "conflicting") for f in involved],
                field=later_role,
            )
        )
    return drafts


RULES = (
    RuleSpec(SAME_ROLE_ID, VERSION, evaluate_same_role),
    RuleSpec(ORDER_ID, VERSION, evaluate_order),
)
