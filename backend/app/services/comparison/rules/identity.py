"""Supplier and buyer names across documents (fuzzy match after normalization)."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations

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
from app.services.entity_resolution.names import name_similarity
from app.services.risk.scoring import bounded

RULE_ID = "identity.parties"
VERSION = "1.0"
PARTIES = {"supplier": "supplier (seller, shipper or exporter)", "buyer": "buyer (consignee)"}


def name_of(obs: FieldObs) -> str:
    return str(obs.normalized.get("name") or obs.value or "")


def evaluate(
    fields: Sequence[FieldObs], docs: Sequence[DocInfo], ctx: RuleContext
) -> list[FindingDraft]:
    drafts = []
    for party, label in PARTIES.items():
        members = [f for f in fields if f.name == party and f.usable and name_of(f)]
        if len({f.document_id for f in members}) < 2:
            continue
        names = sorted({name_of(f) for f in members})
        lowest = min(
            (name_similarity(a, b) for a, b in combinations(names, 2)),
            default=1.0,
        )
        if lowest >= ctx.name_threshold:
            continue
        ordered = sorted(members, key=lambda f: (name_of(f), f.filename))
        drafts.append(
            FindingDraft(
                rule_id=RULE_ID,
                rule_version=VERSION,
                signature=party,
                type="identity_mismatch",
                title=f"The {party} is named differently across documents",
                severity="medium",
                severity_rationale=(
                    f"Medium: the lowest name similarity is {lowest:.2f}, below the threshold "
                    f"{ctx.name_threshold:.2f}."
                ),
                explanation="; ".join(f'{cite(f)} names "{name_of(f)}"' for f in ordered) + ".",
                recommended_action=(
                    f"Confirm whether the named parties are the same {label}, for example "
                    "through registration numbers or addresses."
                ),
                evidence=[EvidenceDraft(f, "conflicting") for f in ordered],
                field=party,
                anomaly_score=bounded(1 - lowest),
                limitations=[
                    "Names can differ legitimately (trading names, agents, group companies). "
                    "Similarity is measured after removing legal suffixes, punctuation and "
                    "letter case, ignoring word order."
                ],
                coverage=coverage_for(party, fields, docs),
                details={"lowest_similarity": lowest, "threshold": ctx.name_threshold},
            )
        )
    return drafts


RULES = (RuleSpec(RULE_ID, VERSION, evaluate),)
