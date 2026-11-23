"""Normalizers for amounts, quantities, dates and names. Ambiguous input returns None.

Money is Decimal plus an ISO 4217 code. A currency is never guessed: "$" alone could be USD,
HKD or CAD, so it yields no currency. Numeric dates where day and month could be swapped
(03/04/2026) yield no date.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

ISO_CURRENCIES = frozenset(
    "USD EUR GBP CNY HKD JPY CHF CAD AUD NZD SGD INR AED SAR PKR KRW MXN BRL ZAR SEK NOK DKK "
    "PLN TRY THB MYR IDR PHP VND".split()
)
UNAMBIGUOUS_SYMBOLS = {
    "€": "EUR",
    "£": "GBP",
    "US$": "USD",
    "HK$": "HKD",
    "C$": "CAD",
    "A$": "AUD",
    "S$": "SGD",
    "₹": "INR",
}
_NUMBER = r"\d{1,3}(?:[,.\s]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_AMOUNT = re.compile(
    rf"^\s*(?P<pre>[A-Z]{{3}}|US\$|HK\$|C\$|A\$|S\$|[€£₹$¥])?\s*(?P<num>{_NUMBER})\s*"
    rf"(?P<post>[A-Z]{{3}})?\s*$"
)
_QUANTITY = re.compile(
    rf"^\s*(?P<num>{_NUMBER})\s*(?P<unit>[A-Za-z][A-Za-z .]{{0,20}})?(?:\(.*\))?\s*$"
)
MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=1,
    )
}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
_LEGAL_SUFFIXES = re.compile(
    r"\b(limited|ltd|inc|incorporated|llc|corp|corporation|co|company|gmbh|plc|sa|bv)\b\.?", re.I
)


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str | None


def parse_number(text: str) -> Decimal | None:
    """Parse grouped numbers: 48,000.00 / 48.000,00 / 48 000 / 1,000. None if ambiguous."""
    s = text.strip().replace("\u00a0", " ")
    if not re.fullmatch(_NUMBER, s):
        return None
    last_sep = max(s.rfind(","), s.rfind("."))
    decimals = ""
    integer = s
    decimal_sep: str | None = None
    # One or two digits after the last separator: that separator is the decimal point.
    if last_sep != -1 and len(s) - last_sep - 1 in (1, 2):
        decimals = s[last_sep + 1 :]
        integer = s[:last_sep]
        decimal_sep = s[last_sep]
    groups = re.split(r"[,.\s]", integer)
    if len(groups) > 1:
        seps = set(re.findall(r"[,.\s]", integer))
        if (
            len(seps) != 1
            or decimal_sep in seps  # one character can't be both grouping and decimal mark
            or any(len(g) != 3 for g in groups[1:])
            or not 1 <= len(groups[0]) <= 3
        ):
            return None
    try:
        return Decimal("".join(groups) + (f".{decimals}" if decimals else ""))
    except InvalidOperation:
        return None


def parse_amount(text: str) -> Money | None:
    match = _AMOUNT.match(text)
    if not match:
        return None
    number = parse_number(match["num"])
    if number is None:
        return None
    pre, post = match["pre"], match["post"]
    if pre and post and pre != post:
        return None
    code = post or pre
    currency: str | None = None
    if code:
        if code in ISO_CURRENCIES:
            currency = code
        elif code in UNAMBIGUOUS_SYMBOLS:
            currency = UNAMBIGUOUS_SYMBOLS[code]
        elif len(code) == 3 and code.isalpha():
            return None  # three letters that aren't a known currency code
    return Money(amount=number.quantize(Decimal("0.01")), currency=currency)


def format_amount(amount: Decimal, currency: str, style: str = "en") -> str:
    """Render an amount the way documents print it (used by property tests)."""
    q = amount.quantize(Decimal("0.01"))
    whole, frac = f"{q:.2f}".split(".")
    grouped = f"{int(whole):,}"
    if style == "de":
        return f"{grouped.replace(',', '.')},{frac} {currency}"
    return f"{currency} {grouped}.{frac}"


def parse_quantity(text: str) -> tuple[Decimal, str | None] | None:
    match = _QUANTITY.match(text)
    if not match:
        return None
    number = parse_number(match["num"])
    if number is None or number < 0:
        return None
    unit = (match["unit"] or "").strip().lower() or None
    return number, unit


def parse_date(text: str) -> date | None:
    s = text.strip().rstrip(".")
    try:
        if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\.?,?\s+(\d{4})", s):
            month = MONTHS.get(m[2].lower())
            return date(int(m[3]), month, int(m[1])) if month else None
        if m := re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", s):
            month = MONTHS.get(m[1].lower())
            return date(int(m[3]), month, int(m[2])) if month else None
        if m := re.fullmatch(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", s):
            a, b, year = int(m[1]), int(m[2]), int(m[3])
            if a > 12 >= b:
                return date(year, b, a)  # day first is the only valid reading
            if b > 12 >= a:
                return date(year, a, b)  # month first is the only valid reading
            return date(year, a, b) if a == b else None  # ambiguous otherwise
    except ValueError:
        return None
    return None


def normalize_name(name: str) -> str:
    """Comparable form of an organization name: casefold, no legal suffix or punctuation."""
    s = _LEGAL_SUFFIXES.sub(" ", name.casefold())
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_reference(ref: str) -> str:
    return re.sub(r"[\s\-_/]", "", ref).upper()


def _plain(text: str) -> str:
    s = re.sub(r"[^\w\s]", " ", text.casefold())
    return re.sub(r"\s+", " ", s).strip()


def normalize_address(address: str) -> str:
    """Comparable form of an address: casefold, punctuation removed, spaces collapsed."""
    return _plain(address)


_LEADING_QUANTITY = re.compile(r"^\s*\d[\d,.]*\s+(?:units?|pcs|pieces|pairs|sets)\b\s*", re.I)
_TRAILING_PACKAGES = re.compile(
    r"[,;]?\s*\d[\d,.]*\s+(?:cartons?|packages?|pallets?|boxes|cases)\s*$", re.I
)


def normalize_product(description: str) -> str:
    """Comparable form of a goods description: the quantity in front ("1,000 units") and the
    package count at the end (", 100 cartons") are removed, then casefold and punctuation."""
    s = _TRAILING_PACKAGES.sub("", _LEADING_QUANTITY.sub("", description))
    return _plain(s)
