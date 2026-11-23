"""Registered comparison rules. Each module exposes RULES: a tuple of RuleSpec."""

from __future__ import annotations

from app.services.comparison.model import RuleSpec
from app.services.comparison.rules import (
    dates,
    duplicates,
    financial,
    identity,
    missing,
    quantity,
    references,
)

ALL_RULES: tuple[RuleSpec, ...] = (
    *financial.RULES,
    *quantity.RULES,
    *references.RULES,
    *identity.RULES,
    *duplicates.RULES,
    *dates.RULES,
    *missing.RULES,
)
