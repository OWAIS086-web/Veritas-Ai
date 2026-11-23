"""Generate the forensic test fixtures (deterministic). SYNTHETIC DEMONSTRATION DATA.

    uv run python scripts/generate_forensics_samples.py

Writes sample-data/forensics/ and its manifest.json (ground truth for tests only; the
application never reads it). Every file is a fictional document. The "edited" variants are
deliberately altered copies, made so the analyses can be tested against known regions.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sample_content import FOOTER, LABEL

OUT = Path(__file__).resolve().parents[2] / "sample-data" / "forensics"
W, H = 595.0, 842.0
FIXED = "D:20261001090000+00'00'"
LATER = "D:20261015164500+00'00'"
SCAN_DPI = 150
TOTAL = "USD 12,500.00"
EDITED_TOTAL = "USD 19,500.00"
STAMP_CENTRE = (430.0, 640.0)


def _stamp(page: pymupdf.Page, line1: str, line2: str, ring: float = 3.0) -> list[float]:
    cx, cy = STAMP_CENTRE
    red = (0.78, 0.08, 0.1)
    page.draw_circle((cx, cy), 52, color=red, width=ring)
    page.draw_circle((cx, cy), 44, color=red, width=1.2)
    for text, dy, size in ((line1, -6, 8.5), ("* APPROVED *", 8, 9.5), (line2, 22, 7.5)):
        width = pymupdf.get_text_length(text, fontname="hebo", fontsize=size)
        page.insert_text((cx - width / 2, cy + dy), text, fontname="hebo", fontsize=size, color=red)
    return [cx - 56, cy - 56, cx + 56, cy + 56]


def _signature(page: pymupdf.Page) -> list[float]:
    blue = (0.1, 0.2, 0.65)
    x, y = 80.0, 655.0
    points = [
        (x, y),
        (x + 20, y - 18),
        (x + 34, y + 10),
        (x + 52, y - 22),
        (x + 70, y + 6),
        (x + 92, y - 14),
        (x + 110, y + 8),
        (x + 140, y - 10),
        (x + 170, y + 2),
    ]
    for a, b, c, d in zip(points, points[1:], points[2:], points[3:], strict=False):
        page.draw_bezier(a, b, c, d, color=blue, width=1.6)
    page.draw_line((x - 4, y + 16), (x + 176, y + 16), color=(0.3, 0.3, 0.3), width=0.5)
    page.insert_text((x, y + 28), "Authorised signatory", fontname="helv", fontsize=8)
    return [x - 4, y - 26, x + 176, y + 18]


def invoice(
    total: str,
    stamp: tuple[str, str] | None,
    title: str = "COMMERCIAL INVOICE",
    number: str = "FX-INV-1001",
    signature: bool = True,
) -> tuple[bytes, dict[str, Any]]:
    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    page.draw_rect(pymupdf.Rect(0, 0, W, 26), color=None, fill=(0.96, 0.62, 0.04))
    page.insert_text((40, 17), LABEL, fontname="hebo", fontsize=10)
    page.insert_text((40, 62), title, fontname="hebo", fontsize=18)
    rows = [
        ("Invoice No", number),
        ("Invoice Date", "1 October 2026"),
        ("Seller", "Forensic Trading Co"),
        ("Buyer", "Northwind Imports LLC"),
        ("Currency", "USD"),
        ("Total Quantity", "250 units"),
        ("Invoice Total", total),
    ]
    y = 110.0
    regions: dict[str, Any] = {}
    for label, value in rows:
        page.insert_text((40, y), f"{label}:", fontname="hebo", fontsize=10)
        page.insert_text((200, y), value, fontname="helv", fontsize=10)
        if label == "Invoice Total":
            regions["total"] = [196.0, y - 11.0, 320.0, y + 4.0]
        y += 20
    page.insert_text(
        (40, y + 20),
        "Goods: 250 units Ceramic Valve Assembly, type CV-20",
        fontname="helv",
        fontsize=10,
    )
    if stamp:
        regions["stamp"] = _stamp(page, *stamp)
    if signature:
        regions["signature"] = _signature(page)
    page.insert_text((40, H - 24), FOOTER, fontname="helv", fontsize=8, color=(0.35, 0.35, 0.35))
    doc.set_metadata(
        {
            "title": f"{title} ({LABEL})",
            "author": "VERITAS forensic fixtures",
            "creator": "VERITAS sample generator",
            "producer": "PyMuPDF",
            "creationDate": FIXED,
            "modDate": FIXED,
            "keywords": "synthetic",
        }
    )
    data: bytes = doc.tobytes(garbage=4, deflate=True, no_new_id=True)
    doc.close()
    return data, regions


def incremental_edit(original: bytes) -> bytes:
    """Replace the total in a different font through an incremental update, by a different
    producer, and stamp a later modification date."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "doc.pdf"
        path.write_bytes(original)
        doc = pymupdf.open(path)
        page = doc[0]
        hit = page.search_for(TOTAL)[0]
        page.add_redact_annot(hit, fill=(1, 1, 1))
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
        page.insert_text((hit.x0, hit.y1 - 2.5), EDITED_TOTAL, fontname="cour", fontsize=10)
        meta = dict(doc.metadata or {})
        meta.update({"producer": "QuickPDF Editor 4.2", "modDate": LATER})
        doc.set_metadata(
            {
                k: v
                for k, v in meta.items()
                if k
                in {
                    "title",
                    "author",
                    "subject",
                    "keywords",
                    "creator",
                    "producer",
                    "creationDate",
                    "modDate",
                }
            }
        )
        # no_new_id keeps the trailer /ID, so the fixture is reproducible byte for byte.
        doc.save(str(path), incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP, no_new_id=True)
        doc.close()
        return path.read_bytes()


def backdated(original: bytes) -> bytes:
    doc = pymupdf.open(stream=original, filetype="pdf")
    meta = dict(doc.metadata or {})
    doc.set_metadata(
        {
            "title": meta.get("title") or "",
            "producer": "PyMuPDF",
            "creationDate": LATER,
            "modDate": FIXED,
        }
    )
    data: bytes = doc.tobytes(garbage=4, deflate=True, no_new_id=True)
    doc.close()
    return data


def _raster(pdf: bytes) -> np.ndarray:
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    pix = doc[0].get_pixmap(dpi=SCAN_DPI, colorspace=pymupdf.csRGB, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3).copy()
    doc.close()
    rng = np.random.default_rng(7)  # the same sensor noise on every scan
    noisy = img.astype(np.int16) + rng.normal(0, 3.0, img.shape).astype(np.int16)
    return np.clip(noisy, 0, 255).astype(np.uint8)


def _scan_pdf(rgb: np.ndarray) -> bytes:
    ok, png = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError("image encoding failed")
    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    page.insert_image(page.rect, stream=png.tobytes())
    doc.set_metadata(
        {
            "title": f"Scanned copy ({LABEL})",
            "producer": "PyMuPDF",
            "creationDate": FIXED,
            "modDate": FIXED,
        }
    )
    data: bytes = doc.tobytes(garbage=4, deflate=True, no_new_id=True)
    doc.close()
    return data


def recompressed(clean_pdf: bytes, region_pt: list[float]) -> tuple[bytes, bytes, list[float]]:
    """A clean scan, and the same scan with one region pasted back from a low-quality JPEG."""
    rgb = _raster(clean_pdf)
    clean_scan = _scan_pdf(rgb)
    s = SCAN_DPI / 72.0
    # Align the pasted block to the JPEG 8-pixel grid, as a cut-and-paste editor would.
    x0, y0 = int(region_pt[0] * s) // 8 * 8 - 64, int(region_pt[1] * s) // 8 * 8 - 32
    x1, y1 = x0 + 384, y0 + 96
    patch = cv2.cvtColor(rgb[y0:y1, x0:x1], cv2.COLOR_RGB2BGR)
    ok, jpg = cv2.imencode(".jpg", patch, [cv2.IMWRITE_JPEG_QUALITY, 12])
    if not ok:
        raise RuntimeError("image encoding failed")
    edited = rgb.copy()
    edited[y0:y1, x0:x1] = cv2.cvtColor(cv2.imdecode(jpg, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    return (
        clean_scan,
        _scan_pdf(edited),
        [round(x0 / s, 1), round(y0 / s, 1), round(x1 / s, 1), round(y1 / s, 1)],
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "versions" / "v1").mkdir(parents=True, exist_ok=True)
    (OUT / "versions" / "v2").mkdir(parents=True, exist_ok=True)
    stamp = ("FORENSIC TRADING CO", "REG. 44-1907")
    clean, regions = invoice(TOTAL, stamp)
    files: dict[str, bytes] = {
        "clean_invoice.pdf": clean,
        "edited_invoice.pdf": incremental_edit(clean),
        "backdated_invoice.pdf": backdated(clean),
        "receipt_same_stamp.pdf": invoice(
            TOTAL, stamp, "PAYMENT RECEIPT", "FX-RC-2001", signature=False
        )[0],
        "receipt_altered_stamp.pdf": invoice(
            TOTAL,
            ("FORENSIC TRADNG CO.", "REG. 44-1970"),
            "PAYMENT RECEIPT",
            "FX-RC-2002",
            signature=False,
        )[0],
        "versions/v1/forensic_invoice.pdf": invoice(TOTAL, stamp, number="FX-INV-1101")[0],
        "versions/v2/forensic_invoice.pdf": invoice("USD 15,800.00", stamp, number="FX-INV-1101")[
            0
        ],
    }
    clean_scan, recompressed_scan, jpeg_region = recompressed(clean, regions["total"])
    files["clean_scan.pdf"] = clean_scan
    files["recompressed_scan.pdf"] = recompressed_scan
    manifest: dict[str, Any] = {
        "label": LABEL,
        "files": {},
        "regions": {
            "total": regions["total"],
            "stamp": regions["stamp"],
            "signature": regions["signature"],
            "jpeg_region": jpeg_region,
        },
        "expected": {
            "clean_invoice.pdf": [],
            "clean_scan.pdf": [],
            "edited_invoice.pdf": [
                "incremental_update",
                "metadata_inconsistency",
                "font_inconsistency",
            ],
            "backdated_invoice.pdf": ["metadata_inconsistency"],
            "recompressed_scan.pdf": ["localized_compression_anomaly"],
            "versions/v2/forensic_invoice.pdf": ["version_difference"],
            "receipt_altered_stamp.pdf": ["stamp_appearance_variation"],
            "receipt_same_stamp.pdf": [],
        },
    }
    for name, data in files.items():
        (OUT / name).write_bytes(data)
        manifest["files"][name] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(files)} files to {OUT}")


if __name__ == "__main__":
    main()
