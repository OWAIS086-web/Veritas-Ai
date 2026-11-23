# Req: document-forensics 1.1-1.3
"""PDF structure analysis on generated fixtures (SYNTHETIC DEMONSTRATION DATA)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.services.forensics import pdf_structure
from app.services.forensics.model import FieldBox

SAMPLES = Path(__file__).resolve().parents[3] / "sample-data"
FORENSICS = SAMPLES / "forensics"
MANIFEST = json.loads((FORENSICS / "manifest.json").read_text(encoding="utf-8"))
TOTAL = FieldBox("f-total", "total_amount", "amount", 1, tuple(MANIFEST["regions"]["total"]))  # type: ignore[arg-type]


def _types(name: str, fields: list[FieldBox] | None = None) -> list[str]:
    result = pdf_structure.analyze((FORENSICS / name).read_bytes(), fields or [TOTAL])
    return sorted(a.type for a in result.anomalies)


def test_clean_fixture_and_every_shipment_sample_have_no_structural_anomaly() -> None:
    assert _types("clean_invoice.pdf") == []
    for pdf in sorted((SAMPLES / "shipment-case").glob("*.pdf")):
        assert pdf_structure.analyze(pdf.read_bytes(), []).anomalies == [], pdf.name


def test_incremental_edit_in_another_font_is_reported_with_its_region() -> None:
    result = pdf_structure.analyze((FORENSICS / "edited_invoice.pdf").read_bytes(), [TOTAL])
    by_type = {a.type: a for a in result.anomalies}
    assert sorted(by_type) == ["font_inconsistency", "incremental_update", "metadata_inconsistency"]
    assert result.details["eof_markers"] == 2
    assert by_type["incremental_update"].severity == "low"
    producers = by_type["metadata_inconsistency"].metrics["producers"]
    assert producers == ["PyMuPDF", "QuickPDF Editor 4.2"]
    font = by_type["font_inconsistency"]
    assert font.severity == "medium" and font.requires_review
    assert font.metrics["font"] == "Courier" and font.metrics["field_id"] == "f-total"
    assert font.page_number == 1 and font.region is not None
    # The reported region covers the replaced total.
    x0, y0, x1, y1 = MANIFEST["regions"]["total"]
    assert font.region[0] <= x1 and font.region[2] >= x0
    assert font.region[1] <= y1 and font.region[3] >= y0


def test_a_rare_font_away_from_extracted_values_is_not_reported() -> None:
    elsewhere = FieldBox("f-x", "document_number", "reference", 1, (40.0, 700.0, 120.0, 712.0))
    assert "font_inconsistency" not in _types("edited_invoice.pdf", [elsewhere])


def test_modification_before_creation_is_flagged_as_low() -> None:
    result = pdf_structure.analyze((FORENSICS / "backdated_invoice.pdf").read_bytes(), [])
    [anomaly] = result.anomalies
    assert anomaly.type == "metadata_inconsistency" and anomaly.severity == "low"


def test_structure_details_are_recorded() -> None:
    details = pdf_structure.analyze((FORENSICS / "clean_invoice.pdf").read_bytes(), []).details
    assert details["metadata"]["producer"] == "PyMuPDF"
    assert details["pages"][0]["fonts"] and details["signature_fields"] == 0
    assert details["eof_markers"] == 1 and details["is_form"] is False


@given(st.datetimes(min_value=datetime(1990, 1, 1), max_value=datetime(2099, 12, 31)))
def test_pdf_dates_round_trip(value: datetime) -> None:
    value = value.replace(microsecond=0)
    text = value.strftime("D:%Y%m%d%H%M%S+00'00'")
    assert pdf_structure.parse_pdf_date(text) == value.replace(tzinfo=UTC)


@pytest.mark.parametrize("text", [None, "", "yesterday", "D:2026", "D:20261399"])
def test_unparseable_dates_are_none_or_partial(text: str | None) -> None:
    parsed = pdf_structure.parse_pdf_date(text)
    assert parsed is None or parsed.year == 2026
