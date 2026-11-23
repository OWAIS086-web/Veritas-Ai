"""Deterministic label-based extractor.

For each field it looks for "Label: value" or "Label | value" at the start of a line, on any
page. The value's box, location and confidence come from the tokens it covers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.extraction.fields import FieldSpec, fields_for
from app.services.extraction.result import (
    EXTRACTED,
    UNCERTAIN,
    ExtractedValue,
    finalize,
    missing,
    normalize,
)
from app.services.parsing.model import ParsedPage

RULES_VERSION = "rules-extract-1.0"


@dataclass(frozen=True)
class Match:
    raw: str
    page: ParsedPage
    line_index: int
    start: int
    end: int


def _pattern(label: str) -> re.Pattern[str]:
    return re.compile(
        rf"^\s*{re.escape(label)}\s*(?::\s*\|?|\|)\s*(?P<v>[^|]*?[^|\s])\s*(?:\||$)",
        re.IGNORECASE,
    )


def find_matches(spec: FieldSpec, pages: list[ParsedPage]) -> list[Match]:
    patterns = [_pattern(label) for label in spec.labels]
    found: list[Match] = []
    for page in pages:
        for index, line in enumerate(page.lines):
            for pattern in patterns:
                m = pattern.match(line.text)
                if m:
                    found.append(Match(m["v"], page, index, m.start("v"), m.end("v")))
                    break
    return found


def _model_version(page: ParsedPage, ocr_version: str | None) -> str:
    if page.method == "ocr" and ocr_version:
        return f"{RULES_VERSION}+{ocr_version}"
    return RULES_VERSION


def _value(
    spec: FieldSpec, match: Match, document_currency: str | None, ocr_version: str | None
) -> ExtractedValue:
    line = match.page.lines[match.line_index]
    bbox, location, confidence = line.span(match.start, match.end)
    normalized, currency, reason = normalize(spec, match.raw, document_currency)
    return ExtractedValue(
        name=spec.name,
        value_type=spec.value_type,
        value=match.raw,
        normalized=normalized,
        currency=currency,
        semantic_role=spec.role,
        confidence=confidence,
        page_number=match.page.page_number,
        bbox=bbox,
        location=location,
        method=match.page.method,
        model_version=_model_version(match.page, ocr_version),
        status=UNCERTAIN if reason else EXTRACTED,
        rejection_reason=reason,
    )


def extract(
    doc_type: str, pages: list[ParsedPage], ocr_version: str | None = None
) -> list[ExtractedValue]:
    specs = fields_for(doc_type)
    page_text = {p.page_number: p.text for p in pages}
    document_currency: str | None = None
    currency_spec = next((s for s in specs if s.value_type == "currency"), None)
    if currency_spec:
        matches = find_matches(currency_spec, pages)
        if matches:
            normalized, _, _ = normalize(currency_spec, matches[0].raw, None)
            document_currency = normalized["currency"] if normalized else None

    results: list[ExtractedValue] = []
    for spec in specs:
        matches = find_matches(spec, pages)
        if not matches:
            if spec.required:
                results.append(missing(spec, "rules", RULES_VERSION, "not_found"))
            continue
        values = [_value(spec, m, document_currency, ocr_version) for m in matches]
        distinct = {str(v.normalized) if v.normalized is not None else v.value for v in values}
        chosen = values[0]
        if len(distinct) > 1:
            chosen = ExtractedValue(
                **{
                    **chosen.__dict__,
                    "status": UNCERTAIN,
                    "rejection_reason": "conflicting_values_on_document",
                }
            )
        results.append(finalize(chosen, page_text.get(chosen.page_number or 0)))
    return results
