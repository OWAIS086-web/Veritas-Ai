"""Schema validation of normalized values before persistence (Pydantic).

A value that doesn't fit its schema becomes null and uncertain with the validation reason.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.services.extraction.normalize import ISO_CURRENCIES
from app.services.extraction.result import UNCERTAIN, ExtractedValue

Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AmountValue(_Strict):
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    currency: Currency | None


class DateValue(_Strict):
    date: date
    role: str | None


class QuantityValue(_Strict):
    quantity: Decimal = Field(ge=0, max_digits=18)
    unit: str | None


class CurrencyValue(_Strict):
    currency: Currency


class PartyValue(_Strict):
    name: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    key: str


class ReferenceValue(_Strict):
    reference: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    key: str


class TextValue(_Strict):
    text: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class KeyedTextValue(_Strict):
    """Addresses and goods descriptions: the printed text and its comparable key."""

    text: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    key: Annotated[str, StringConstraints(min_length=1, max_length=500)]


SCHEMAS: dict[str, type[BaseModel]] = {
    "amount": AmountValue,
    "date": DateValue,
    "quantity": QuantityValue,
    "currency": CurrencyValue,
    "party": PartyValue,
    "reference": ReferenceValue,
    "text": TextValue,
    "address": KeyedTextValue,
    "product": KeyedTextValue,
}


def validate_value(value: ExtractedValue) -> ExtractedValue:
    if value.normalized is None:
        return value
    schema = SCHEMAS.get(value.value_type)
    reason: str | None = None
    if schema is None:
        reason = f"no_schema_for_type:{value.value_type}"
    else:
        try:
            schema.model_validate(value.normalized)
        except ValidationError as exc:
            reason = (
                "schema_invalid:"
                + ",".join(".".join(str(p) for p in e["loc"]) for e in exc.errors())[:150]
            )
    currency = value.normalized.get("currency") if isinstance(value.normalized, dict) else None
    if reason is None and currency is not None and currency not in ISO_CURRENCIES:
        reason = "unknown_currency_code"
    if reason is None:
        return value
    return replace(
        value,
        value=None,
        normalized=None,
        currency=None,
        confidence=None,
        bbox=None,
        status=UNCERTAIN,
        rejection_reason=reason,
    )


def validate_values(values: list[ExtractedValue]) -> list[ExtractedValue]:
    return [validate_value(v) for v in values]
