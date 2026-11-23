# Req: document-intelligence 3.1-3.5
"""Parsers, OCR and layout on the real synthetic sample files."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.ocr.preprocess import estimate_skew, map_points, preprocess
from app.services.ocr.service import decode_image, ocr_image
from app.services.parsing import layout, office
from app.services.parsing.model import Line, Token, assemble_lines, detect_language
from app.services.parsing.pdf import has_text_layer, open_pdf, parse_text_page, render_page

SAMPLES = Path(__file__).resolve().parents[3] / "sample-data"
CASE = SAMPLES / "shipment-case"
VARIANTS = SAMPLES / "format-variants"
MANIFEST = json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))["files"]


def _pdf_pages(path: Path) -> list:
    with open_pdf(path.read_bytes()) as doc:
        return [parse_text_page(doc[i], i + 1) for i in range(len(doc))]


@pytest.mark.parametrize("name", sorted(p.name for p in CASE.glob("*.pdf")))
def test_text_layer_pdfs_contain_their_ground_truth(name: str) -> None:
    truth = MANIFEST[f"shipment-case/{name}"]
    pages = _pdf_pages(CASE / name)
    text = "\n".join(p.text for p in pages)
    assert truth["document_number"] in text
    assert "SYNTHETIC DEMONSTRATION DATA" in text
    for page in pages:
        assert page.method == "text_layer" and page.coord_unit == "pt"
        for line in page.lines:
            for tok in line.tokens:
                x0, y0, x1, y1 = tok.bbox  # type: ignore[misc]
                assert 0 <= x0 < x1 <= page.width and 0 <= y0 < y1 <= page.height


def test_label_and_value_share_a_line_with_a_cell_separator() -> None:
    pages = _pdf_pages(CASE / "03_customs_declaration.pdf")
    line = next(ln for ln in pages[1].lines if "Declared Customs Value" in ln.text)
    assert line.text == "Declared Customs Value: | USD 68,000.00"
    start = line.text.index("68,000.00")
    bbox, _, conf = line.span(start, start + len("68,000.00"))
    assert bbox is not None and conf == 1.0
    assert bbox[0] > 150  # the value column, not the label


def test_scanned_pdf_has_no_text_layer() -> None:
    with open_pdf((VARIANTS / "commercial_invoice_scanned.pdf").read_bytes()) as doc:
        assert not has_text_layer(doc[0])
    with open_pdf((CASE / "02_commercial_invoice.pdf").read_bytes()) as doc:
        assert has_text_layer(doc[0])


def test_docx_parser_keeps_locations() -> None:
    [page] = office.parse_docx((VARIANTS / "commercial_invoice.docx").read_bytes())
    line = next(ln for ln in page.lines if ln.text.startswith("Invoice Total"))
    assert line.text == "Invoice Total: USD 48,000.00"
    assert line.location is not None and line.location.startswith("paragraph ")
    table_line = next(ln for ln in page.lines if "9405.42" in ln.text)
    assert table_line.location == "table 1 row 2"


def test_xlsx_parser_gives_cell_references() -> None:
    [page] = office.parse_xlsx((VARIANTS / "packing_list.xlsx").read_bytes())
    line = next(ln for ln in page.lines if ln.text.startswith("Total Quantity"))
    start = line.text.index("1,000 units")
    _, location, _ = line.span(start, start + 3)
    assert location is not None and location.startswith("Packing List!B")


def test_csv_and_eml_parsers() -> None:
    [csv_page] = office.parse_csv((VARIANTS / "commercial_invoice.csv").read_bytes())
    assert any(ln.text == "Invoice Total | USD 48,000.00" for ln in csv_page.lines)
    [eml_page], attachments = office.parse_eml((VARIANTS / "payment_advice.eml").read_bytes())
    assert attachments == []
    assert any(ln.text == "Amount Paid: USD 48,000.00" for ln in eml_page.lines)
    assert eml_page.lines[0].location == "header From"


def test_language_detection() -> None:
    text = "\n".join(p.text for p in _pdf_pages(CASE / "02_commercial_invoice.pdf"))
    assert detect_language(text) == "en"
    assert detect_language("12 34 56") is None


def test_deskew_recovers_a_known_rotation() -> None:
    with open_pdf((CASE / "02_commercial_invoice.pdf").read_bytes()) as doc:
        rgb = render_page(doc[0], dpi=100)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    rotated = cv2.warpAffine(
        gray, cv2.getRotationMatrix2D((w / 2, h / 2), 1.5, 1.0), (w, h), borderValue=255
    )
    assert abs(estimate_skew(rotated) + 1.5) <= 0.2
    assert abs(estimate_skew(gray)) <= 0.1


@settings(max_examples=50)
@given(
    st.floats(-5, 5),
    st.lists(st.tuples(st.floats(0, 1000), st.floats(0, 1000)), min_size=1, max_size=8),
)
def test_inverse_transform_round_trips_points(
    angle: float, points: list[tuple[float, float]]
) -> None:
    forward = cv2.getRotationMatrix2D((400, 500), angle, 1.0)
    inverse = cv2.invertAffineTransform(forward)
    pts = np.array(points)
    assert np.allclose(map_points(map_points(pts, forward), inverse), pts, atol=1e-6)


@given(st.lists(st.text(alphabet="abcXYZ019,.:", min_size=1, max_size=6), min_size=1, max_size=6))
def test_line_offsets_map_back_to_each_token(words: list[str]) -> None:
    tokens = [Token(text=w, bbox=(i * 50.0, 0, i * 50.0 + 40, 10)) for i, w in enumerate(words)]
    line = Line.build(tokens)
    for tok in line.tokens:
        assert line.text[tok.start : tok.end] == tok.text
        bbox, _, _ = line.span(tok.start, tok.end)
        assert bbox == tok.bbox
    restored = Line.from_json(line.to_json())
    assert restored.text == line.text and [t.text for t in restored.tokens] == words


def test_assemble_lines_orders_top_to_bottom_left_to_right() -> None:
    toks = [
        Token("B", (300, 10, 320, 20)),
        Token("A", (10, 11, 30, 21)),
        Token("C", (10, 40, 30, 50)),
    ]
    lines = assemble_lines(toks)
    assert [ln.text for ln in lines] == ["A | B", "C"]


@pytest.mark.slow
def test_ocr_reads_the_scanned_invoice_with_page_coordinates() -> None:
    with open_pdf((VARIANTS / "commercial_invoice_scanned.pdf").read_bytes()) as doc:
        rgb = render_page(doc[0], dpi=200)
        width, height = doc[0].rect.width, doc[0].rect.height
    page, metrics = ocr_image(rgb, 1, points_per_pixel=72 / 200)
    assert page.method == "ocr" and page.coord_unit == "pt"
    assert abs(metrics["deskew_degrees"]) > 0.3  # the scan was generated with a 0.7 degree skew
    assert "INV-2026-1042" in page.text
    total = next(ln for ln in page.lines if "Invoice Total" in ln.text)
    assert "48,000.00" in total.text
    conf = [t.confidence for t in total.tokens]
    assert all(c is not None and 0 < c <= 1 for c in conf)
    # Boxes land where the text-layer original has the same words (within a few points).
    with open_pdf((CASE / "02_commercial_invoice.pdf").read_bytes()) as doc:
        ref = parse_text_page(doc[0], 1)
    ref_line = next(ln for ln in ref.lines if "Invoice Total" in ln.text)
    assert total.bbox is not None and ref_line.bbox is not None
    assert abs(total.bbox[1] - ref_line.bbox[1]) < 6 and abs(total.bbox[0] - ref_line.bbox[0]) < 6
    assert 0 <= total.bbox[0] and total.bbox[2] <= width and total.bbox[3] <= height


@pytest.mark.slow
@pytest.mark.parametrize(
    "name", ["purchase_order.png", "payment_receipt.jpg", "bill_of_lading.tiff"]
)
def test_ocr_reads_image_formats(name: str) -> None:
    truth = MANIFEST[f"format-variants/{name}"]
    [rgb] = decode_image((VARIANTS / name).read_bytes())
    page, _ = ocr_image(rgb, 1, points_per_pixel=None)
    assert page.coord_unit == "px"
    assert truth["document_number"] in page.text.replace(" ", "")


def test_preprocess_keeps_image_size() -> None:
    img = np.full((200, 300, 3), 255, dtype=np.uint8)
    out = preprocess(img)
    assert out.image.shape == (200, 300, 3) and out.angle == 0.0


@pytest.mark.slow
def test_docling_extracts_the_invoice_line_item_table() -> None:
    data = (CASE / "02_commercial_invoice.pdf").read_bytes()
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        heights = {i + 1: doc[i].rect.height for i in range(len(doc))}
    tables = layout.extract_tables(data, heights, timeout_seconds=600)
    rows = tables[1][0]["rows"]
    flat = " ".join(" ".join(r) for r in rows)
    assert "9405.42" in flat and "48,000.00" in flat
    x0, y0, x1, y1 = tables[1][0]["bbox"]
    assert 0 <= x0 < x1 <= 595 and 0 <= y0 < y1 <= 842
