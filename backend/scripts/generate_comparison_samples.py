"""Generate the document-comparison fixtures (deterministic). SYNTHETIC DEMONSTRATION DATA.

    uv run python scripts/generate_comparison_samples.py

Writes sample-data/comparison/ and its manifest.json (ground truth for tests only; the
application never reads it):

- original_invoice.pdf        two-page commercial invoice (the reference)
- test_altered.pdf            the same invoice with the total, the invoice date and the bank
                              account changed (digital edit)
- test_resaved.pdf            the same content saved again with other metadata (no visible
                              change; a negative control)
- test_scanned_altered.png    page 1 of the altered invoice printed and scanned: rotated,
                              shifted and noisy (alignment has to recover it)

Every file is a fictional document; the altered ones are deliberately changed copies.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sample_content import FOOTER, LABEL

OUT = Path(__file__).resolve().parents[2] / "sample-data" / "comparison"
W, H = 595.0, 842.0
FIXED = "D:20261001090000+00'00'"
LATER = "D:20261020120000+00'00'"
SCAN_DPI = 150
SCAN_ANGLE = 1.2  # degrees
SCAN_SHIFT = (14, -9)  # pixels

ORIGINAL = {
    "total": "USD 48,000.00",
    "date": "3 October 2026",
    "account": "DE44 5001 0517 5407 3249 31",
}
ALTERED = {
    "total": "USD 68,000.00",
    "date": "8 October 2026",
    "account": "DE44 5001 0517 9907 3249 31",
}


def _page_one(page: pymupdf.Page, v: dict[str, str]) -> None:
    page.draw_rect(pymupdf.Rect(0, 0, W, 26), color=None, fill=(0.96, 0.62, 0.04))
    page.insert_text((40, 17), LABEL, fontname="hebo", fontsize=10)
    page.insert_text((40, 62), "COMMERCIAL INVOICE", fontname="hebo", fontsize=18)
    rows = [
        ("Invoice No", "CMP-INV-3001"),
        ("Invoice Date", v["date"]),
        ("Seller", "Harbour Ceramics Ltd"),
        ("Buyer", "Northwind Imports LLC"),
        ("Purchase Order", "PO-77120"),
        ("Currency", "USD"),
        ("Total Quantity", "400 units"),
        ("Invoice Total", v["total"]),
    ]
    y = 110.0
    for label, value in rows:
        page.insert_text((40, y), f"{label}:", fontname="hebo", fontsize=10)
        page.insert_text((200, y), value, fontname="helv", fontsize=10)
        y += 20
    page.insert_text(
        (40, y + 20),
        "Goods: 400 units Ceramic Valve Assembly, type CV-20",
        fontname="helv",
        fontsize=10,
    )
    page.insert_text((40, H - 24), FOOTER, fontname="helv", fontsize=8, color=(0.35, 0.35, 0.35))


def _page_two(page: pymupdf.Page, v: dict[str, str]) -> None:
    page.draw_rect(pymupdf.Rect(0, 0, W, 26), color=None, fill=(0.96, 0.62, 0.04))
    page.insert_text((40, 17), LABEL, fontname="hebo", fontsize=10)
    page.insert_text((40, 62), "PAYMENT INSTRUCTIONS", fontname="hebo", fontsize=14)
    rows = [
        ("Beneficiary", "Harbour Ceramics Ltd"),
        ("Bank", "Example Merchant Bank"),
        ("IBAN", v["account"]),
        ("Terms", "30 days net"),
    ]
    y = 100.0
    for label, value in rows:
        page.insert_text((40, y), f"{label}:", fontname="hebo", fontsize=10)
        page.insert_text((200, y), value, fontname="helv", fontsize=10)
        y += 20
    page.insert_text((40, H - 24), FOOTER, fontname="helv", fontsize=8, color=(0.35, 0.35, 0.35))


def invoice(v: dict[str, str], producer: str = "PyMuPDF", mod: str = FIXED) -> bytes:
    doc = pymupdf.open()
    _page_one(doc.new_page(width=W, height=H), v)
    _page_two(doc.new_page(width=W, height=H), v)
    doc.set_metadata(
        {
            "title": f"Commercial invoice CMP-INV-3001 ({LABEL})",
            "author": "VERITAS comparison fixtures",
            "creator": "VERITAS sample generator",
            "producer": producer,
            "creationDate": FIXED,
            "modDate": mod,
            "keywords": "synthetic",
        }
    )
    data: bytes = doc.tobytes(garbage=4, deflate=True, no_new_id=True)
    doc.close()
    return data


def regions(pdf: bytes, v: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Where the changed values sit (page, box in points), from the PDF itself."""
    out: dict[str, dict[str, Any]] = {}
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        for key, page_no in (("total", 1), ("date", 1), ("account", 2)):
            hit = doc[page_no - 1].search_for(v[key])[0]
            out[key] = {
                "page": page_no,
                "box": [round(c, 1) for c in (hit.x0, hit.y0, hit.x1, hit.y1)],
            }
    return out


def scanned(pdf: bytes) -> tuple[bytes, np.ndarray]:
    """Page 1 rendered, rotated, shifted and noisy, as a print-and-scan would make it."""
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        pix = doc[0].get_pixmap(dpi=SCAN_DPI, colorspace=pymupdf.csRGB, alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3).copy()
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), SCAN_ANGLE, 1.0)
    m[:, 2] += SCAN_SHIFT
    warped = cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR, borderValue=(250, 250, 248))
    rng = np.random.default_rng(11)
    noisy = np.clip(
        warped.astype(np.int16) + rng.normal(0, 4.0, warped.shape).astype(np.int16), 0, 255
    )
    ok, png = cv2.imencode(".png", cv2.cvtColor(noisy.astype(np.uint8), cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError("image encoding failed")
    return png.tobytes(), m


def _scan_box(box: list[float], m: np.ndarray) -> list[float]:
    s = SCAN_DPI / 72.0
    pts = np.array(
        [
            [box[0] * s, box[1] * s, 1],
            [box[2] * s, box[1] * s, 1],
            [box[2] * s, box[3] * s, 1],
            [box[0] * s, box[3] * s, 1],
        ]
    ).T
    mapped = m @ pts
    return [
        round(float(v), 1)
        for v in (mapped[0].min(), mapped[1].min(), mapped[0].max(), mapped[1].max())
    ]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    original = invoice(ORIGINAL)
    altered = invoice(ALTERED, producer="QuickPDF Editor 4.2", mod=LATER)
    resaved = invoice(ORIGINAL, producer="Print to PDF 2.0", mod=LATER)
    scan, m = scanned(altered)
    files = {
        "original_invoice.pdf": original,
        "test_altered.pdf": altered,
        "test_resaved.pdf": resaved,
        "test_scanned_altered.png": scan,
    }
    changed = regions(altered, ALTERED)
    manifest: dict[str, Any] = {
        "label": LABEL,
        "files": {},
        "original": "original_invoice.pdf",
        "changes": {
            key: {"original": ORIGINAL[key], "test": ALTERED[key], **changed[key]}
            for key in ALTERED
        },
        "expected": {
            "test_altered.pdf": ["total", "date", "account"],
            "test_resaved.pdf": [],
            # The scan is page 1 only: page 2 of the original has no counterpart.
            "test_scanned_altered.png": ["total", "date", "page_removed:2"],
        },
        "scan": {
            "dpi": SCAN_DPI,
            "angle_degrees": SCAN_ANGLE,
            "shift_px": list(SCAN_SHIFT),
            "boxes_px": {k: _scan_box(v["box"], m) for k, v in changed.items() if v["page"] == 1},
        },
    }
    for name, data in files.items():
        (OUT / name).write_bytes(data)
        manifest["files"][name] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUT / "README.md").write_text(
        f"# Document comparison samples\n\n**{LABEL}**\n\nFictional files for the Document "
        "Comparison Lab demo. Compare `original_invoice.pdf` (original) with each `test_*` file. "
        "`manifest.json` lists the deliberate changes and where they are; the application never "
        "reads it.\n\nRegenerate with `uv run python scripts/generate_comparison_samples.py` "
        "(from `backend/`).\n",
        encoding="utf-8",
    )
    print(f"wrote {len(files)} files to {OUT}")


if __name__ == "__main__":
    main()
