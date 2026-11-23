"""Generate the synthetic shipment case and its format variants (deterministic).

    uv run python scripts/generate_samples.py

Writes:
    sample-data/shipment-case/*.pdf          the 7 demo documents (text-layer PDFs)
    sample-data/format-variants/*            scanned PDF, PNG, JPG, TIFF, DOCX, XLSX, CSV, EML
    sample-data/manifest.json                ground truth for tests (never read by the app)
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pymupdf
from docx import Document as DocxDocument
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sample_content import DOCUMENTS, FOOTER, GROUND_TRUTH, LABEL

ROOT = Path(__file__).resolve().parents[2] / "sample-data"
CASE_DIR = ROOT / "shipment-case"
VARIANT_DIR = ROOT / "format-variants"
FIXED_DATE = "D:20261101000000Z"
ZIP_EPOCH = (2026, 11, 1, 0, 0, 0)
W, H = 595.0, 842.0  # A4 in points


def _page(
    doc: pymupdf.Document, title: str, page_no: int, pages: int
) -> tuple[pymupdf.Page, float]:
    page = doc.new_page(width=W, height=H)
    page.draw_rect(pymupdf.Rect(0, 0, W, 26), color=None, fill=(0.96, 0.62, 0.04))
    page.insert_text((40, 17), LABEL, fontname="hebo", fontsize=10, color=(0, 0, 0))
    page.insert_text((40, 62), title, fontname="hebo", fontsize=18)
    page.insert_text((W - 110, 62), f"Page {page_no} of {pages}", fontname="helv", fontsize=9)
    page.draw_line((40, 72), (W - 40, 72), color=(0.6, 0.6, 0.6), width=0.6)
    page.insert_text((40, H - 24), FOOTER, fontname="helv", fontsize=8, color=(0.35, 0.35, 0.35))
    return page, 100.0


def _render_blocks(page: pymupdf.Page, blocks: list[tuple[Any, ...]], y: float) -> None:
    for block in blocks:
        kind = block[0]
        if kind == "kv":
            page.insert_text((40, y), f"{block[1]}:", fontname="hebo", fontsize=10)
            page.insert_text((200, y), str(block[2]), fontname="helv", fontsize=10)
            y += 18
        elif kind == "heading":
            y += 6
            page.insert_text((40, y), block[1], fontname="hebo", fontsize=12)
            y += 22
        elif kind == "note":
            y += 8
            page.insert_text((40, y), block[1], fontname="helv", fontsize=9)
            y += 18
        elif kind == "table":
            headers, rows = block[1], block[2]
            cols = len(headers)
            # Column widths (points) per table shape; the description column is the wide one.
            widths_by_cols = {
                5: [44.0, 196.0, 85.0, 85.0, 105.0],
                6: [32.0, 168.0, 60.0, 60.0, 70.0, 125.0],
            }
            widths = widths_by_cols.get(cols, [(W - 80) / cols] * cols)
            y += 6
            for r, row in enumerate([headers, *rows]):
                x = 40.0
                font = "hebo" if r == 0 else "helv"
                for cell, w in zip(row, widths, strict=True):
                    page.insert_text((x + 2, y), str(cell), fontname=font, fontsize=8.5)
                    x += w
                page.draw_line((40, y + 5), (W - 40, y + 5), color=(0.7, 0.7, 0.7), width=0.4)
                y += 18
            y += 8


def build_pdf(name: str) -> bytes:
    spec = DOCUMENTS[name]
    doc = pymupdf.open()
    pages = spec["pages"]
    for i, blocks in enumerate(pages, start=1):
        page, y = _page(doc, spec["title"], i, len(pages))
        _render_blocks(page, blocks, y)
    doc.set_metadata(
        {
            "title": f"{spec['title']} ({LABEL})",
            "author": "VERITAS sample generator",
            "subject": LABEL,
            "creator": "VERITAS sample generator",
            "producer": "PyMuPDF",
            "creationDate": FIXED_DATE,
            "modDate": FIXED_DATE,
            "keywords": "synthetic",
        }
    )
    data: bytes = doc.tobytes(garbage=4, deflate=True, no_new_id=True)
    doc.close()
    return data


def render_png(pdf: bytes, page_index: int = 0, dpi: int = 150) -> np.ndarray:
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    pix = doc[page_index].get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3).copy()
    doc.close()
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


def scan_effect(img: np.ndarray, seed: int, angle: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gray = gray * 0.93 + 10 + rng.normal(0, 6, gray.shape)
    gray = np.clip(gray, 0, 255).astype(np.uint8)
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(gray, m, (w, h), borderValue=245)


def scanned_pdf(pdf: bytes, seed: int) -> bytes:
    """Rasterize each page with noise and a slight skew, and keep no text layer."""
    src = pymupdf.open(stream=pdf, filetype="pdf")
    out = pymupdf.open()
    for i in range(len(src)):
        img = scan_effect(render_png(pdf, i, dpi=200), seed + i, angle=0.7)
        ok, png = cv2.imencode(".png", img)
        if not ok:
            raise RuntimeError("PNG encoding failed")
        page = out.new_page(width=W, height=H)
        page.insert_image(page.rect, stream=png.tobytes())
    out.set_metadata(
        {
            "title": f"Scanned copy ({LABEL})",
            "producer": "PyMuPDF",
            "creationDate": FIXED_DATE,
            "modDate": FIXED_DATE,
        }
    )
    data: bytes = out.tobytes(garbage=4, deflate=True, no_new_id=True)
    src.close()
    out.close()
    return data


def normalize_zip(data: bytes) -> bytes:
    """Rewrite a ZIP-based office file with fixed timestamps so its hash is stable."""
    src = zipfile.ZipFile(io.BytesIO(data))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in sorted(src.infolist(), key=lambda i: i.filename):
            fixed = zipfile.ZipInfo(info.filename, date_time=ZIP_EPOCH)
            fixed.compress_type = zipfile.ZIP_DEFLATED
            fixed.external_attr = 0o644 << 16
            content = src.read(info.filename)
            if info.filename == "docProps/core.xml":
                # openpyxl stamps "modified" with the current time on save.
                content = re.sub(
                    rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:)",
                    rb"\g<1>2026-11-01T00:00:00Z\g<2>",
                    content,
                )
            dst.writestr(fixed, content)
    return buf.getvalue()


def _kv_rows(name: str) -> list[tuple[str, str]]:
    return [(b[1], str(b[2])) for page in DOCUMENTS[name]["pages"] for b in page if b[0] == "kv"]


def build_docx(name: str) -> bytes:
    from datetime import UTC, datetime

    spec = DOCUMENTS[name]
    d = DocxDocument()
    d.core_properties.created = datetime(2026, 11, 1, tzinfo=UTC)
    d.core_properties.modified = datetime(2026, 11, 1, tzinfo=UTC)
    d.core_properties.author = "VERITAS sample generator"
    d.core_properties.title = f"{spec['title']} ({LABEL})"
    d.add_paragraph(LABEL)
    d.add_heading(spec["title"], level=1)
    for page in spec["pages"]:
        for block in page:
            if block[0] == "kv":
                d.add_paragraph(f"{block[1]}: {block[2]}")
            elif block[0] == "note":
                d.add_paragraph(block[1])
            elif block[0] == "table":
                table = d.add_table(rows=1, cols=len(block[1]))
                for cell, text in zip(table.rows[0].cells, block[1], strict=True):
                    cell.text = text
                for row in block[2]:
                    cells = table.add_row().cells
                    for cell, text in zip(cells, row, strict=True):
                        cell.text = str(text)
    d.add_paragraph(FOOTER)
    buf = io.BytesIO()
    d.save(buf)
    return normalize_zip(buf.getvalue())


def build_xlsx(name: str) -> bytes:
    from datetime import datetime

    spec = DOCUMENTS[name]
    wb = Workbook()
    wb.properties.created = datetime(2026, 11, 1)
    wb.properties.modified = datetime(2026, 11, 1)
    wb.properties.creator = "VERITAS sample generator"
    ws = wb.active
    if ws is None:
        raise RuntimeError("workbook has no sheet")
    ws.title = "Packing List"
    ws.append([LABEL])
    ws.append([spec["title"]])
    for label, value in _kv_rows(name):
        ws.append([label, value])
    for page in spec["pages"]:
        for block in page:
            if block[0] == "table":
                ws.append([])
                ws.append(list(block[1]))
                for row in block[2]:
                    ws.append([str(c) for c in row])
    ws.append([FOOTER])
    buf = io.BytesIO()
    wb.save(buf)
    return normalize_zip(buf.getvalue())


def build_csv(name: str) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["field", "value"])
    writer.writerow(["notice", LABEL])
    writer.writerow(["Document Type", DOCUMENTS[name]["title"].title()])
    for label, value in _kv_rows(name):
        writer.writerow([label, value])
    return buf.getvalue().encode("utf-8")


def build_eml() -> bytes:
    msg = EmailMessage()
    msg["From"] = "treasury@abc-imports.example"
    msg["To"] = "accounts@global-trading.example"
    msg["Subject"] = f"Payment advice RCPT-2026-0907 ({LABEL})"
    msg["Date"] = "Fri, 02 Oct 2026 09:30:00 +0000"
    msg["Message-ID"] = "<rcpt-2026-0907@abc-imports.example>"
    lines = [LABEL, "", "PAYMENT RECEIPT", ""]
    lines += [f"{label}: {value}" for label, value in _kv_rows("05_payment_receipt")]
    lines += ["", FOOTER]
    msg.set_content("\n".join(lines))
    return msg.as_bytes()


def _write(path: Path, data: bytes, manifest: dict[str, Any], truth: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    manifest[str(path.relative_to(ROOT)).replace("\\", "/")] = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        **truth,
    }


def main() -> None:
    manifest: dict[str, Any] = {}
    pdfs = {name: build_pdf(name) for name in DOCUMENTS}
    for name, data in pdfs.items():
        _write(CASE_DIR / f"{name}.pdf", data, manifest, GROUND_TRUTH[name])

    po, inv, rcpt, bol = (
        pdfs["01_purchase_order"],
        pdfs["02_commercial_invoice"],
        pdfs["05_payment_receipt"],
        pdfs["07_bill_of_lading"],
    )
    variants: dict[str, tuple[bytes, str]] = {
        "commercial_invoice_scanned.pdf": (scanned_pdf(inv, seed=7), "02_commercial_invoice"),
        "purchase_order.png": (
            cv2.imencode(".png", render_png(po))[1].tobytes(),
            "01_purchase_order",
        ),
        "payment_receipt.jpg": (
            cv2.imencode(
                ".jpg", scan_effect(render_png(rcpt), 11, 0.0), [cv2.IMWRITE_JPEG_QUALITY, 88]
            )[1].tobytes(),
            "05_payment_receipt",
        ),
        "bill_of_lading.tiff": (
            cv2.imencode(".tiff", render_png(bol))[1].tobytes(),
            "07_bill_of_lading",
        ),
        "commercial_invoice.docx": (build_docx("02_commercial_invoice"), "02_commercial_invoice"),
        "packing_list.xlsx": (build_xlsx("06_packing_list"), "06_packing_list"),
        "commercial_invoice.csv": (build_csv("02_commercial_invoice"), "02_commercial_invoice"),
        "payment_advice.eml": (build_eml(), "05_payment_receipt"),
    }
    for filename, (data, source) in variants.items():
        truth = {k: v for k, v in GROUND_TRUTH[source].items() if k != "total_page"}
        _write(VARIANT_DIR / filename, data, manifest, {"source": source, **truth})

    (ROOT / "manifest.json").write_text(
        json.dumps({"label": LABEL, "files": manifest}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (ROOT / "README.md").write_text(
        f"# {LABEL}\n\nFictional documents for the VERITAS AI demo case "
        '"International Shipment Financial Discrepancy Investigation". All companies, people, '
        "references and amounts are invented. Regenerate with "
        "`uv run python backend/scripts/generate_samples.py`.\n\n"
        "- `shipment-case/`: the 7 demo PDFs (PO, invoice and receipt declare USD 48,000; "
        "customs declaration and insurance certificate declare USD 68,000; packing list and "
        "bill of lading both list 1,000 units).\n"
        "- `format-variants/`: the same content as scanned PDF, PNG, JPG, TIFF, DOCX, XLSX, "
        "CSV and EML, used to test each ingestion path.\n"
        "- `manifest.json`: hashes and ground truth used **only by tests**.\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {len(manifest)} files to {ROOT}")


if __name__ == "__main__":
    main()
