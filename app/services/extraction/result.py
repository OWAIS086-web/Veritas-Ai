"""Typed extraction result with full provenance, plus normalization and validation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from app.services.extraction.fields import FieldSpec
from app.services.extraction.normalize import (
    ISO_CURRENCIES,
    normalize_address,
    normalize_name,
    normalize_product,
    normalize_reference,
    parse_amount,
    parse_date,
    parse_quantity,
)
from app.services.extraction.verify import value_is_supported
from app.services.parsing.model import BBox

EXTRACTED = "extracted"
UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class ExtractedValue:
    name: str
    value_type: str
    value: str | None
    normalized: dict[str, Any] | None
    currency: str | None
    semantic_role: str | None
    confidence: float | None
    page_number: int | None
    bbox: BBox | None
    location: str | None
    method: str
    model_version: str
    status: str
    rejection_reason: str | None = None


def missing(spec: FieldSpec, method: str, model_version: str, reason: str) -> ExtractedValue:
    """A failed extraction: null value, explicitly uncertain. Never a guess."""
    return ExtractedValue(
        name=spec.name,
        value_type=spec.value_type,
        value=None,
        normalized=None,
        currency=None,
        semantic_role=spec.role,
        confidence=None,
        page_number=None,
        bbox=None,
        location=None,
        method=method,
        model_version=model_version,
        status=UNCERTAIN,
        rejection_reason=reason,
    )


def normalize(
    spec: FieldSpec, raw: str, document_currency: str | None
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """Return (normalized_value, currency, rejection_reason)."""
    if spec.value_type == "amount":
        money = parse_amount(raw)
        if money is None:
            return None, None, "unparseable_amount"
        currency = money.currency or document_currency
        normalized = {"amount": str(money.amount), "currency": currency}
        if currency is None:
            return normalized, None, "currency_unknown"
        if money.currency and document_currency and money.currency != document_currency:
            return normalized, currency, "currency_conflicts_with_document_currency"
        return normalized, currency, None
    if spec.value_type == "date":
        parsed = parse_date(raw)
        if parsed is None:
            return None, None, "unparseable_or_ambiguous_date"
        return {"date": parsed.isoformat(), "role": spec.role}, None, None
    if spec.value_type == "quantity":
        quantity = parse_quantity(raw)
        if quantity is None:
            return None, None, "unparseable_quantity"
        return {"quantity": str(quantity[0]), "unit": quantity[1]}, None, None
    if spec.value_type == "currency":
        code = raw.strip().upper()
        if code not in ISO_CURRENCIES:
            return None, None, "unknown_currency_code"
        return {"currency": code}, code, None
    if spec.value_type == "party":
        return {"name": raw.strip(), "key": normalize_name(raw)}, None, None
    if spec.value_type == "reference":
        return {"reference": raw.strip(), "key": normalize_reference(raw)}, None, None
    if spec.value_type == "address":
        return {"text": raw.strip(), "key": normalize_address(raw)}, None, None
    if spec.value_type == "product":
        key = normalize_product(raw)
        if not key:
            return None, None, "unparseable_product"
        return {"text": raw.strip(), "key": key}, None, None
    return {"text": raw.strip()}, None, None


def finalize(value: ExtractedValue, page_text: str | None) -> ExtractedValue:
    """Anti-fabrication: a value that isn't on its cited page becomes null and uncertain."""
    if value.value is None:
        return value
    if page_text is None or not value_is_supported(value.value, page_text):
        return replace(
            value,
            value=None,
            normalized=None,
            currency=None,
            confidence=None,
            bbox=None,
            status=UNCERTAIN,
            rejection_reason="value_not_on_cited_page",
        )
    return value
