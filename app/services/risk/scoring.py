"""Three separate values per finding, each computed from persisted data only.

- anomaly_score: how large the observed inconsistency is (0..1). It measures magnitude, not
  likelihood of wrongdoing.
- evidence_confidence: the lowest measured confidence of the cited fields. Null when no
  evidence exists or any cited field has no measured confidence (it is never invented).
- priority: what to review first, from a fixed matrix of severity and evidence confidence.

None of these is a probability of fraud, and nothing here produces one.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

SEVERITIES = ("info", "low", "medium", "high")
STRONG_CONFIDENCE = Decimal("0.9")
_STEP = Decimal("0.001")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_STEP, rounding=ROUND_HALF_UP)


def relative_difference(values: Iterable[Decimal]) -> Decimal:
    """(max - min) / max, capped at 1. Zero when all values are equal or the max is 0."""
    items = list(values)
    if not items:
        return Decimal(0)
    high, low = max(items), min(items)
    if high <= 0:
        return Decimal(0)
    return _q(min(Decimal(1), (high - low) / high))


def bounded(value: float | Decimal) -> Decimal:
    return _q(min(Decimal(1), max(Decimal(0), Decimal(str(value)))))


def severity_for_relative(rel: Decimal) -> str:
    if rel >= Decimal("0.10"):
        return "high"
    if rel >= Decimal("0.02"):
        return "medium"
    return "low"


def evidence_confidence(confidences: Iterable[Decimal | None]) -> Decimal | None:
    items = list(confidences)
    if not items or any(c is None for c in items):
        return None
    return _q(min(c for c in items if c is not None))


@dataclass(frozen=True)
class Priority:
    level: str  # low | medium | high
    rationale: str


def priority(severity: str, confidence: Decimal | None, evidence_status: str) -> Priority:
    if severity not in SEVERITIES:
        raise ValueError(f"unknown severity {severity!r}")
    base = {"high": "high", "medium": "medium"}.get(severity, "low")
    if evidence_status == "absence":
        return Priority(base, f"Severity {severity}; based on an absence, so no field confidence.")
    if confidence is not None and confidence >= STRONG_CONFIDENCE:
        return Priority(base, f"Severity {severity} with evidence confidence {confidence}.")
    lowered = {"high": "medium", "medium": "low"}.get(base, "low")
    reason = (
        "no measured confidence for at least one cited field"
        if confidence is None
        else f"evidence confidence {confidence} is below {STRONG_CONFIDENCE}"
    )
    return Priority(lowered, f"Severity {severity}, lowered one level: {reason}.")
