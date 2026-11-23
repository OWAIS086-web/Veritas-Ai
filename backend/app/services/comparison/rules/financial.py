"""Financial reconciliation of document totals (`total_amount`).

Amounts are compared only within one currency. Different currencies produce an
informational `currency_mismatch` observation and are never compared with each other.
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
    money,
)
from app.services.risk.scoring import relative_difference, severity_for_relative

FIELD = "total_amount"
RULE_ID = "financial.total_amount"
CURRENCY_RULE_ID = "financial.currency"
VERSION = "1.0"


def amount_of(obs: FieldObs) -> Decimal:
    return Decimal(str(obs.normalized["amount"]))


def currency_of(obs: FieldObs) -> str | None:
    value = obs.normalized.get("currency") if isinstance(obs.normalized, dict) else None
    return value or obs.currency


def _by_currency(fields: Sequence[FieldObs]) -> dict[str, list[FieldObs]]:
    groups: dict[str, list[FieldObs]] = defaultdict(list)
    for f in fields:
        if f.name == FIELD and f.usable and (cur := currency_of(f)):
            groups[cur].append(f)
    return dict(groups)


def _role(obs: FieldObs) -> str:
    return (obs.role or "total").replace("_", " ")


def _context(fields: Sequence[FieldObs], evidence_types: set[str | None]) -> list[str]:
    """Stated terms that can explain part of a difference. Reported as limitations only."""
    notes: list[str] = []
    terms = [f for f in fields if f.usable and f.name in {"incoterms", "valuation_basis"}]
    for f in sorted(terms, key=lambda x: (x.filename, x.name)):
        label = "Incoterms" if f.name == "incoterms" else "valuation basis"
        notes.append(f'{cite(f)} states {label} "{f.value}".')
    if len(terms) > 1:
        notes.append(
            "Values stated on different delivery or valuation terms (for example FOB and "
            "CIF) are not directly comparable: a CIF value includes freight and insurance."
        )
    if "insurance_certificate" in evidence_types:
        notes.append(
            "An insured value can be set above the invoice value by the policy terms, so it "
            "is not by itself a declaration of the goods' price."
        )
    return notes


def evaluate_amounts(
    fields: Sequence[FieldObs], docs: Sequence[DocInfo], ctx: RuleContext
) -> list[FindingDraft]:
    drafts: list[FindingDraft] = []
    for currency, group in sorted(_by_currency(fields).items()):
        if len({f.document_id for f in group}) < 2:
            continue
        values = [amount_of(f) for f in group]
        high, low = max(values), min(values)
        if high <= 0 or (high - low) / high <= ctx.amount_tolerance:
            continue
        rel = relative_difference(values)
        difference = high - low
        ordered = sorted(group, key=lambda f: (amount_of(f), f.filename))
        by_value: dict[Decimal, list[FieldObs]] = defaultdict(list)
        for f in ordered:
            by_value[amount_of(f)].append(f)
        lines = [
            f"{currency} {money(v)}: " + "; ".join(f"{cite(f)}, {_role(f)}" for f in items)
            for v, items in sorted(by_value.items())
        ]
        severity = severity_for_relative(rel)
        drafts.append(
            FindingDraft(
                rule_id=RULE_ID,
                rule_version=VERSION,
                signature=f"{FIELD}:{currency}",
                type="financial_discrepancy",
                title=f"Declared totals differ by {currency} {money(difference)}",
                severity=severity,
                severity_rationale=(
                    f"The difference is {rel:.1%} of the highest value. Thresholds: 10% or "
                    "more is high, 2% or more is medium, otherwise low."
                ),
                explanation=(
                    f"{len(group)} documents state a total in {currency}, and they do not "
                    "agree.\n"
                    + "\n".join(lines)
                    + f"\nThe difference between the highest and lowest value is {currency} "
                    f"{money(difference)}."
                ),
                recommended_action=(
                    "Review each cited value on its page, then obtain the basis of each "
                    "declared amount (valuation terms, freight, insurance) from the parties "
                    "that issued the documents."
                ),
                evidence=[EvidenceDraft(f, "conflicting") for f in ordered],
                field=FIELD,
                currency=currency,
                difference=difference,
                anomaly_score=rel,
                limitations=_context(fields, {f.doc_type for f in group}),
                coverage=coverage_for(FIELD, fields, docs),
                details={
                    "values": {
                        str(v): [str(f.document_id) for f in items] for v, items in by_value.items()
                    },
                    "tolerance": str(ctx.amount_tolerance),
                    "relative_difference": str(rel),
                },
            )
        )
    return drafts


def evaluate_currencies(
    fields: Sequence[FieldObs], docs: Sequence[DocInfo], ctx: RuleContext
) -> list[FindingDraft]:
    groups = _by_currency(fields)
    if len(groups) < 2:
        return []
    currencies = sorted(groups)
    observations = sorted(
        (f for items in groups.values() for f in items), key=lambda f: (f.filename, f.name)
    )
    return [
        FindingDraft(
            rule_id=CURRENCY_RULE_ID,
            rule_version=VERSION,
            signature=f"{FIELD}:{','.join(currencies)}",
            type="currency_mismatch",
            title="Totals are stated in different currencies: " + ", ".join(currencies),
            severity="info",
            severity_rationale=(
                "Informational: amounts in different currencies are not compared, because "
                "no exchange rate is part of the case evidence."
            ),
            explanation="; ".join(
                f"{cite(f)} states {currency_of(f)} {money(amount_of(f))}" for f in observations
            )
            + ".",
            recommended_action=(
                "Confirm which currency each document was issued in and whether a conversion "
                "was agreed."
            ),
            evidence=[EvidenceDraft(f, "context") for f in observations],
            field=FIELD,
            coverage=coverage_for(FIELD, fields, docs),
        )
    ]


RULES = (
    RuleSpec(RULE_ID, VERSION, evaluate_amounts),
    RuleSpec(CURRENCY_RULE_ID, VERSION, evaluate_currencies),
)
