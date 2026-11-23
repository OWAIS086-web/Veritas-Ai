"""Invariants of the comparison rules."""

from __future__ import annotations

import random
from datetime import date
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from app.services.comparison.rules import dates, financial
from tests.unit.comparison_fixtures import CTX, Case

amounts = st.decimals(min_value=1, max_value=10**8, places=2, allow_nan=False)
currencies = st.sampled_from(["USD", "EUR", "GBP", "JPY"])
DOC_TYPES = ["purchase_order", "commercial_invoice", "customs_declaration", "payment_receipt"]


def _amount_case(values: list[tuple[Decimal, str]]) -> Case:
    c = Case()
    for i, (amount, currency) in enumerate(values):
        doc = c.doc(DOC_TYPES[i % len(DOC_TYPES)], f"doc{i:02d}.pdf")
        c.amount(doc, str(amount), currency)
    return c


def _summary(c: Case) -> list[tuple[str, Decimal | None, int]]:
    return sorted(
        (d.key, d.difference, len(d.evidence))
        for d in financial.evaluate_amounts(c.fields, c.docs, CTX)
    )


@given(st.lists(st.tuples(amounts, currencies), min_size=2, max_size=6), st.randoms())
def test_amount_comparison_is_order_independent(
    values: list[tuple[Decimal, str]], rnd: random.Random
) -> None:
    c = _amount_case(values)
    expected = _summary(c)
    rnd.shuffle(c.fields)
    assert _summary(c) == expected


@given(amounts, amounts)
def test_amount_comparison_is_symmetric(a: Decimal, b: Decimal) -> None:
    assert _summary(_amount_case([(a, "USD"), (b, "USD")])) == _summary(
        _amount_case([(b, "USD"), (a, "USD")])
    )


@given(st.lists(amounts, min_size=1, max_size=4), st.lists(amounts, min_size=1, max_size=4))
def test_different_currencies_never_produce_a_financial_finding(
    usd: list[Decimal], eur: list[Decimal]
) -> None:
    c = Case()
    for i, v in enumerate(usd[:1]):
        c.amount(c.doc("commercial_invoice", f"u{i}.pdf"), str(v), "USD")
    for i, v in enumerate(eur[:1]):
        c.amount(c.doc("customs_declaration", f"e{i}.pdf"), str(v), "EUR")
    # One document per currency: nothing is comparable, whatever the values.
    assert financial.evaluate_amounts(c.fields, c.docs, CTX) == []
    for draft in financial.evaluate_currencies(c.fields, c.docs, CTX):
        assert draft.type == "currency_mismatch" and draft.difference is None


@given(st.lists(st.tuples(amounts, currencies), min_size=2, max_size=6))
def test_a_finding_cites_every_value_of_its_currency_only(
    values: list[tuple[Decimal, str]],
) -> None:
    c = _amount_case(values)
    for draft in financial.evaluate_amounts(c.fields, c.docs, CTX):
        cited = {e.obs.field_id for e in draft.evidence}
        same = {f.field_id for f in c.fields if f.currency == draft.currency}
        assert cited == same
        values_cited = [Decimal(e.obs.normalized["amount"]) for e in draft.evidence]
        assert draft.difference == max(values_cited) - min(values_cited)


@given(
    st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)),
    st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)),
)
def test_dates_with_different_roles_never_conflict(a: date, b: date) -> None:
    c = Case()
    c.date(c.doc("purchase_order", "po.pdf"), "order_date", a.isoformat())
    c.date(c.doc("commercial_invoice", "inv.pdf"), "invoice_date", b.isoformat())
    c.date(c.doc("packing_list", "pl.pdf"), "packing_date", b.isoformat())
    assert dates.evaluate_same_role(c.fields, c.docs, CTX) == []
