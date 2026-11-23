# Req: document-forensics 2.1-2.3, 3.1-3.3
"""Visual analyses on generated fixtures (SYNTHETIC DEMONSTRATION DATA): the edited cases are
found at their known regions, and clean documents raise nothing."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.forensics import MANDATORY_LIMITATION
from app.services.forensics import imaging, stamps, versions, visual
from app.services.forensics.analyze import Settings, analyze_document
from app.services.forensics.model import FieldBox, overlaps

SAMPLES = Path(__file__).resolve().parents[3] / "sample-data"
F = SAMPLES / "forensics"
MANIFEST = json.loads((F / "manifest.json").read_text(encoding="utf-8"))
REGIONS = MANIFEST["regions"]
S = Settings(dpi=110, max_pages=20, noise_k=6.0, version_ssim=0.6, stamp_threshold=0.004)
TOTAL = FieldBox("f-total", "total_amount", "amount", 1, tuple(REGIONS["total"]))  # type: ignore[arg-type]


def _rasters(name: str) -> list[imaging.Raster]:
    return imaging.pdf_rasters((F / name).read_bytes(), S.dpi, S.max_pages)


def test_recompressed_region_is_found_where_it_was_pasted() -> None:
    result = visual.analyze(_rasters("recompressed_scan.pdf"), [TOTAL], S.noise_k)
    [anomaly] = result.anomalies
    assert anomaly.type == "localized_compression_anomaly"
    assert anomaly.region is not None and overlaps(anomaly.region, REGIONS["jpeg_region"])
    # It covers the extracted total, so it is ranked for review (and never above medium).
    assert anomaly.severity == "medium" and anomaly.metrics["fields"] == ["f-total"]
    assert anomaly.metrics["region_noise"] < anomaly.metrics["page_median_noise"] / 2


@pytest.mark.parametrize(
    ("folder", "name"),
    [
        ("forensics", "clean_scan.pdf"),
        ("forensics", "clean_invoice.pdf"),
        ("format-variants", "commercial_invoice_scanned.pdf"),
        *(("shipment-case", p.name) for p in sorted((SAMPLES / "shipment-case").glob("*.pdf"))),
    ],
)
def test_clean_documents_raise_no_compression_anomaly(folder: str, name: str) -> None:
    rasters = imaging.pdf_rasters((SAMPLES / folder / name).read_bytes(), S.dpi, S.max_pages)
    assert visual.analyze(rasters, [], S.noise_k).anomalies == []


@pytest.mark.parametrize(
    "name", ["purchase_order.png", "payment_receipt.jpg", "bill_of_lading.tiff"]
)
def test_image_files_raise_no_compression_anomaly(name: str) -> None:
    rasters = imaging.image_rasters((SAMPLES / "format-variants" / name).read_bytes(), S.max_pages)
    assert visual.analyze(rasters, [], S.noise_k).anomalies == []


def test_pages_drawn_from_a_text_layer_are_not_measured() -> None:
    result = visual.analyze(_rasters("clean_invoice.pdf"), [], S.noise_k)
    assert result.details["pages"][0]["status"] == "not_applicable"


def test_version_difference_is_found_on_the_changed_total() -> None:
    old, new = (
        _rasters("versions/v1/forensic_invoice.pdf"),
        _rasters("versions/v2/forensic_invoice.pdf"),
    )
    [anomaly] = versions.analyze(old, new, [TOTAL], S.version_ssim).anomalies
    assert anomaly.type == "version_difference" and anomaly.region is not None
    assert overlaps(anomaly.region, REGIONS["total"]) and anomaly.severity == "medium"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            "forensics/versions/v1/forensic_invoice.pdf",
            "forensics/versions/v1/forensic_invoice.pdf",
        ),
        ("forensics/clean_invoice.pdf", "forensics/clean_scan.pdf"),
        (
            "shipment-case/02_commercial_invoice.pdf",
            "format-variants/commercial_invoice_scanned.pdf",
        ),
    ],
)
def test_unchanged_content_is_not_a_version_difference(old: str, new: str) -> None:
    a = imaging.pdf_rasters((SAMPLES / old).read_bytes(), S.dpi, S.max_pages)
    b = imaging.pdf_rasters((SAMPLES / new).read_bytes(), S.dpi, S.max_pages)
    assert versions.analyze(a, b, [], S.version_ssim).anomalies == []


def _stamp_of(name: str) -> dict[str, object]:
    regions = [r for ra in _rasters(name) for r in stamps.find_regions(ra) if r.kind == "stamp"]
    return {**regions[0].to_json(), "document_id": "d-ref", "filename": name}


def test_stamps_and_signatures_are_located() -> None:
    found = [r for ra in _rasters("clean_invoice.pdf") for r in stamps.find_regions(ra)]
    kinds = {r.kind: r.region for r in found}
    assert set(kinds) == {"stamp", "signature"}
    assert overlaps(kinds["stamp"], REGIONS["stamp"]) and overlaps(
        kinds["signature"], REGIONS["signature"]
    )
    for pdf in sorted((SAMPLES / "shipment-case").glob("*.pdf")):
        rasters = imaging.pdf_rasters(pdf.read_bytes(), S.dpi, S.max_pages)
        assert [r for ra in rasters for r in stamps.find_regions(ra)] == [], pdf.name


def test_an_altered_repeated_stamp_is_flagged_and_the_same_stamp_is_not() -> None:
    reference = [_stamp_of("clean_invoice.pdf")]
    altered = stamps.analyze(_rasters("receipt_altered_stamp.pdf"), reference, S.stamp_threshold)
    [anomaly] = altered.anomalies
    assert anomaly.type == "stamp_appearance_variation" and anomaly.severity == "medium"
    for name in ("receipt_same_stamp.pdf", "clean_scan.pdf"):
        assert stamps.analyze(_rasters(name), reference, S.stamp_threshold).anomalies == [], name


def test_every_document_report_has_the_mandatory_limitation_and_known_types() -> None:
    expected = MANIFEST["expected"]
    for name, types in expected.items():
        if name.startswith("versions/") or "stamp" in name:
            continue  # need another document (previous version or another stamp)
        report = analyze_document((F / name).read_bytes(), "application/pdf", [TOTAL], S)
        assert report.limitations[0] == MANDATORY_LIMITATION
        assert sorted({a.type for a in report.anomalies}) == sorted(set(types)), name
        assert report.status == "succeeded"
        assert all(a.severity in {"info", "low", "medium"} for a in report.anomalies)
    office = analyze_document(b"a,b\n1,2\n", "text/csv", [], S)
    assert office.status == "not_applicable" and office.limitations[0] == MANDATORY_LIMITATION


def test_a_failing_analysis_is_isolated() -> None:
    report = analyze_document(b"%PDF-1.7 not really a pdf", "application/pdf", [], S)
    assert report.status == "partial" and "pdf_structure" in report.structure["errors"]
    assert report.limitations[0] == MANDATORY_LIMITATION


masks = st.integers(0, 2**32 - 1).map(
    lambda seed: (np.random.default_rng(seed).random((48, 48)) > 0.85).astype(np.uint8) * 255
)


@settings(max_examples=30, deadline=None)
@given(masks, masks)
def test_unmatched_ink_is_symmetric_bounded_and_zero_for_equal_masks(
    a: np.ndarray, b: np.ndarray
) -> None:
    value = stamps.unmatched_ink(a, b)
    assert 0.0 <= value <= 1.0
    assert value == pytest.approx(stamps.unmatched_ink(b, a))
    assert stamps.unmatched_ink(a, a) == 0.0
