"""Risk scoring: three separate values, none of them a fraud probability."""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.services.risk import scoring

amounts = st.decimals(min_value=0, max_value=10**9, places=2, allow_nan=False)
confidences = st.decimals(min_value=0, max_value=1, places=3, allow_nan=False)


@given(st.lists(amounts, min_size=1, max_size=8))
def test_relative_difference_is_bounded_and_order_independent(values: list[Decimal]) -> None:
    rel = scoring.relative_difference(values)
    assert Decimal(0) <= rel <= Decimal(1)
    assert rel == scoring.relative_difference(list(reversed(values)))
    assert rel == scoring.relative_difference(sorted(values))


@given(amounts)
def test_equal_values_have_no_difference(value: Decimal) -> None:
    assert scoring.relative_difference([value, value, value]) == 0


def test_demo_case_difference() -> None:
    rel = scoring.relative_difference([Decimal(48000)] * 3 + [Decimal(68000)] * 2)
    assert rel == Decimal("0.294")
    assert scoring.severity_for_relative(rel) == "high"


@given(st.lists(confidences, min_size=1, max_size=6))
def test_evidence_confidence_is_the_minimum(values: list[Decimal]) -> None:
    assert scoring.evidence_confidence(values) == min(values).quantize(Decimal("0.001"))


@given(st.lists(st.one_of(st.none(), confidences), min_size=1, max_size=6))
def test_unmeasured_confidence_is_never_invented(values: list[Decimal | None]) -> None:
    result = scoring.evidence_confidence(values)
    assert (result is None) == any(v is None for v in values)


def test_no_evidence_has_no_confidence() -> None:
    assert scoring.evidence_confidence([]) is None


@given(
    st.sampled_from(scoring.SEVERITIES),
    st.one_of(st.none(), confidences),
    st.sampled_from(["supported", "absence"]),
)
def test_priority_never_exceeds_severity(
    severity: str, confidence: Decimal | None, evidence_status: str
) -> None:
    order = {"low": 0, "medium": 1, "high": 2}
    ceiling = {"info": 0, "low": 0, "medium": 1, "high": 2}[severity]
    result = scoring.priority(severity, confidence, evidence_status)
    assert order[result.level] <= ceiling
    assert result.rationale


def test_weak_or_unmeasured_confidence_lowers_priority() -> None:
    assert scoring.priority("high", Decimal("1.000"), "supported").level == "high"
    assert scoring.priority("high", Decimal("0.500"), "supported").level == "medium"
    assert scoring.priority("high", None, "supported").level == "medium"
    assert scoring.priority("medium", None, "absence").level == "medium"


def test_unknown_severity_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown severity"):
        scoring.priority("critical", None, "supported")


def test_no_fraud_probability_anywhere() -> None:
    assert not any("fraud" in f.name for f in dataclasses.fields(scoring.Priority))
    app_dir = Path(__file__).resolve().parents[2] / "app"
    for path in app_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "fraud_probability" not in text, path
        assert "fraud_score" not in text, path
