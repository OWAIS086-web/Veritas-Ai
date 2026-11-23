# Req: document-intelligence 4.4; steering document-processing (normalization)
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.services.extraction.normalize import (
    ISO_CURRENCIES,
    Money,
    format_amount,
    normalize_name,
    normalize_reference,
    parse_amount,
    parse_date,
    parse_number,
    parse_quantity,
)

amounts = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("999999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
currencies = st.sampled_from(sorted(ISO_CURRENCIES))


@given(amounts, currencies, st.sampled_from(["en", "de"]))
def test_formatted_amounts_round_trip(amount: Decimal, currency: str, style: str) -> None:
    assert parse_amount(format_amount(amount, currency, style)) == Money(amount, currency)


@given(amounts)
def test_currency_is_never_invented(amount: Decimal) -> None:
    text = format_amount(amount, "USD").removeprefix("USD ")
    parsed = parse_amount(text)
    assert parsed is not None and parsed.currency is None
    dollar = parse_amount("$" + text)
    assert dollar is not None and dollar.currency is None  # "$" alone is ambiguous


@given(st.integers(min_value=0, max_value=10**9))
def test_grouped_integers_parse_to_themselves(n: int) -> None:
    assert parse_number(f"{n:,}") == Decimal(n)
    assert parse_number(str(n)) == Decimal(n)


@given(st.dates(min_value=date(1990, 1, 1), max_value=date(2100, 12, 31)))
def test_unambiguous_date_formats_round_trip(d: date) -> None:
    for text in (
        d.isoformat(),
        f"{d.day} {d:%B} {d.year}",
        f"{d:%B} {d.day}, {d.year}",
        f"{d.day} {d:%b} {d.year}",
    ):
        assert parse_date(text) == d, text


@given(st.dates(min_value=date(1990, 1, 1), max_value=date(2100, 12, 31)))
def test_numeric_dates_are_parsed_only_when_unambiguous(d: date) -> None:
    parsed = parse_date(f"{d.day:02d}/{d.month:02d}/{d.year}")
    if d.day > 12 or d.day == d.month:
        assert parsed == d
    else:
        assert parsed is None  # could be day-first or month-first: never guess


@given(st.text(max_size=40))
def test_name_normalization_is_idempotent(name: str) -> None:
    once = normalize_name(name)
    assert normalize_name(once) == once


@given(st.text(alphabet="ABCDEF0123456789-/ _", max_size=20))
def test_reference_normalization_is_idempotent(ref: str) -> None:
    assert normalize_reference(normalize_reference(ref)) == normalize_reference(ref)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("USD 48,000.00", Money(Decimal("48000.00"), "USD")),
        ("48.000,00 EUR", Money(Decimal("48000.00"), "EUR")),
        ("€1.250,50", Money(Decimal("1250.50"), "EUR")),
        ("US$ 68,000", Money(Decimal("68000.00"), "USD")),
        ("GBP 1 250.00", Money(Decimal("1250.00"), "GBP")),
        ("48,000.00", Money(Decimal("48000.00"), None)),
    ],
)
def test_amount_examples(text: str, expected: Money) -> None:
    assert parse_amount(text) == expected


@pytest.mark.parametrize(
    "text", ["USD 48,00,000", "USD 1,000.000", "ZZZ 100", "USD 100 EUR", "about 48k", "1.000,000"]
)
def test_ambiguous_or_invalid_amounts_are_rejected(text: str) -> None:
    assert parse_amount(text) is None


def test_names_and_quantities() -> None:
    assert normalize_name("GLOBAL TRADING LIMITED") == normalize_name("Global Trading Ltd")
    assert normalize_name("ABC Imports Inc.") == "abc imports"
    assert parse_quantity("1,000 units") == (Decimal("1000"), "units")
    assert parse_quantity("1,000 units (100 cartons)") == (Decimal("1000"), "units")
    assert parse_quantity("1,250 kg") == (Decimal("1250"), "kg")
    assert parse_quantity("many") is None


@given(st.text(max_size=80))
def test_address_and_product_normalization_is_idempotent(text: str) -> None:
    from app.services.extraction.normalize import normalize_address, normalize_product

    assert normalize_address(normalize_address(text)) == normalize_address(text)
    once = normalize_product(text)
    assert normalize_product(once) == once


@given(st.integers(min_value=1, max_value=10**6), st.integers(min_value=1, max_value=10**4))
def test_quantity_and_package_counts_do_not_change_the_product_key(qty: int, cartons: int) -> None:
    from app.services.extraction.normalize import normalize_product

    base = "LED Panel Light 600x600 mm, 40 W"
    assert normalize_product(f"{qty:,} units {base}") == normalize_product(base)
    assert normalize_product(f"{base}, {cartons} cartons") == normalize_product(base)
    assert normalize_product(base) == "led panel light 600x600 mm 40 w"
