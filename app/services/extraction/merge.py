"""Combine model claims with the deterministic extractor, recording every substitution."""

from __future__ import annotations

from typing import Any

from app.services.extraction.result import EXTRACTED, ExtractedValue


def merge_llm_with_rules(
    llm_values: list[ExtractedValue], rules_values: list[ExtractedValue]
) -> tuple[list[ExtractedValue], dict[str, Any]]:
    """Keep each verified model value. Where the model's claim was rejected and the rules
    extractor verified the same field, the rules value stands in; each field records the
    method that produced it. Returns the values and the notes describing each rejection
    (field name and reason only, never document text)."""
    rules_by_name = {v.name: v for v in rules_values}
    values: list[ExtractedValue] = []
    rejected: dict[str, str] = {}
    replaced: list[str] = []
    for v in llm_values:
        if v.status == EXTRACTED:
            values.append(v)
            continue
        rejected[v.name] = v.rejection_reason or v.status
        stand_in = rules_by_name.get(v.name)
        if stand_in is not None and stand_in.status == EXTRACTED:
            values.append(stand_in)
            replaced.append(v.name)
        else:
            values.append(v)
    return values, {"llm_rejected": rejected, "replaced_by_rules": sorted(replaced)}
