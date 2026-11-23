"""The comparison report (PDF with side-by-side crops of both documents), the findings list
appended to the annotated PDF, and the findings JSON.

All three are rendered from one payload built from the persisted comparison rows, so every
finding they show is a stored `comparison_findings` row. Document text and filenames are
untrusted: they are HTML-escaped before rendering.
"""

from __future__ import annotations

import html
import json
from typing import Any

import cv2
import numpy as np
import pymupdf

from app.integrations.pdf.story import render_story, soft_break
from app.services.doccompare.geometry import clip, expand, valid
from app.services.doccompare.pages import page_sizes, rasters
from app.services.forensics.imaging import Raster

SCHEMA = "veritas.document-comparison.v1"
MAX_CROPS = 40
CROP_WIDTH = 520
CSS = """
body { font-family: sans-serif; font-size: 9pt; color: #1f2937; }
h1 { font-size: 16pt; margin: 0 0 4pt 0; }
h2 { font-size: 12pt; margin: 12pt 0 4pt 0; }
h3 { font-size: 10pt; margin: 10pt 0 2pt 0; }
p { margin: 2pt 0; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 1px solid #d1d5db; padding: 2pt 3pt; vertical-align: top; text-align: left; }
th { background-color: #f3f4f6; }
.muted { color: #6b7280; }
.medium { color: #b91c1c; font-weight: bold; }
.low { color: #b45309; font-weight: bold; }
.info { color: #1d4ed8; }
.hash { font-family: monospace; font-size: 7pt; }
"""


def findings_json(payload: dict[str, Any]) -> bytes:
    return json.dumps({"schema": SCHEMA, **payload}, indent=2, ensure_ascii=False).encode()


def _e(value: Any) -> str:
    # Long unbroken values may wrap; escaping comes after so entities stay whole.
    return html.escape(soft_break("" if value is None else str(value)))


def _render(body: str, archive: pymupdf.Archive | None = None) -> bytes:
    return render_story(f"<html><body>{body}</body></html>", CSS, archive=archive)


def _documents_table(payload: dict[str, Any]) -> str:
    rows = []
    for label, key in (("Original", "original"), ("Test", "test")):
        d = payload.get(key) or {}
        rows.append(
            f"<tr><td>{label}</td><td>{_e(d.get('filename'))}</td><td>{_e(d.get('mime_type'))}"
            f"</td><td>{_e(d.get('pages_compared'))}</td>"
            f"<td class='hash'>{_e(d.get('sha256'))}</td></tr>"
        )
    return (
        "<table><tr><th>Role</th><th>File</th><th>Type</th><th>Pages compared</th>"
        f"<th>SHA-256 of the stored file</th></tr>{''.join(rows)}</table>"
    )


def _findings_table(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "<p>No differences were found between the compared pages.</p>"
    rows = []
    for f in findings:
        sev = _e(f.get("severity"))
        sources = _e(", ".join(f.get("sources") or []))
        rows.append(
            f"<tr><td>#{_e(f.get('number'))}</td><td>{_e(f.get('type'))}</td>"
            f"<td>{_e(f.get('test_page') or '-')}</td><td class='{sev}'>{sev}</td>"
            f"<td>{_e(f.get('evidence_confidence'))}</td><td>{sources}</td>"
            f"<td>{_e(f.get('review_status'))}</td><td>{_e(f.get('explanation'))}</td></tr>"
        )
    return (
        "<table><tr><th>#</th><th>Type</th><th>Test page</th><th>Severity</th><th>Evidence "
        "confidence</th><th>Sources</th><th>Review</th><th>Observation</th></tr>"
        f"{''.join(rows)}</table>"
    )


def _header(payload: dict[str, Any], title: str) -> str:
    c = payload.get("comparison") or {}
    vlm = (payload.get("summary") or {}).get("vlm") or {}
    vlm_line = f"Vision model: {_e(c.get('vlm_status'))}"
    if c.get("vlm_model"):
        vlm_line += f" ({_e(c.get('vlm_model'))}, {_e(vlm.get('calls', 0))} calls)"
    return (
        f"<h1>{_e(title)}</h1><p class='muted'>Comparison {_e(c.get('id'))} - generated "
        f"{_e(payload.get('generated_at'))}</p><p>{vlm_line}</p>"
    )


def _limitations(payload: dict[str, Any]) -> str:
    items = "".join(f"<li>{_e(x)}</li>" for x in payload.get("limitations") or [])
    return f"<h2>Limitations</h2><ul>{items}</ul>"


def findings_list_pdf(payload: dict[str, Any]) -> bytes:
    """The pages appended to the annotated PDF: what each numbered mark is."""
    body = (
        _header(payload, "VERITAS AI - annotated differences")
        + _documents_table(payload)
        + "<h2>Numbered differences</h2>"
        + _findings_table(payload.get("findings") or [])
        + _limitations(payload)
    )
    return _render(body)


def _crop(r: Raster, region: list[float], page_w: float, page_h: float) -> bytes | None:
    box = clip(expand(region, 12, 8), page_w, page_h) if valid(region) else None
    if box is None:
        return None
    ox, oy = r.offset
    h, w = r.rgb.shape[:2]
    x0, y0 = max(0, int((box[0] - ox) / r.scale)), max(0, int((box[1] - oy) / r.scale))
    x1 = min(w, int(np.ceil((box[2] - ox) / r.scale)))
    y1 = min(h, int(np.ceil((box[3] - oy) / r.scale)))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    crop = r.rgb[y0:y1, x0:x1]
    if crop.shape[1] > CROP_WIDTH:
        f = CROP_WIDTH / crop.shape[1]
        crop = cv2.resize(
            crop, (CROP_WIDTH, max(1, round(crop.shape[0] * f))), interpolation=cv2.INTER_AREA
        )
    ok, png = cv2.imencode(".png", cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
    return png.tobytes() if ok else None


def report_pdf(
    payload: dict[str, Any],
    original: tuple[bytes, str],
    test: tuple[bytes, str],
    dpi: int,
    max_pages: int,
) -> bytes:
    """The forensic comparison report with crops of both documents for each difference."""
    o_rs = rasters(original[0], original[1], dpi, max_pages)
    t_rs = rasters(test[0], test[1], dpi, max_pages)
    o_sizes = page_sizes(original[0], original[1], o_rs)
    t_sizes = page_sizes(test[0], test[1], t_rs)
    archive = pymupdf.Archive()
    sections: list[str] = []
    findings = payload.get("findings") or []
    for f in findings[:MAX_CROPS]:
        cells = []
        for side, rs, sizes, page, region in (
            ("Original", o_rs, o_sizes, f.get("original_page"), f.get("original_region")),
            ("Test", t_rs, t_sizes, f.get("test_page"), f.get("region")),
        ):
            png = None
            if page and region and 1 <= page <= len(rs):
                png = _crop(rs[page - 1], region, *sizes[page - 1])
            if png is None:
                cells.append(f"<td><p class='muted'>{side}: no region on this side</p></td>")
                continue
            name = f"f{f.get('number')}-{side.lower()}.png"
            archive.add(png, name)
            cells.append(
                f"<td><p><b>{side}</b> page {_e(page)}</p><img src='{name}' width='240'/></td>"
            )
        basis = "".join(f"<li>{_e(b)}</li>" for b in f.get("confidence_basis") or [])
        fields = ", ".join(
            f"{_e(x.get('document'))}: {_e(x.get('name'))} = {_e(x.get('value'))}"
            for x in f.get("extracted_fields") or []
        )
        vlm = f.get("vlm_assessment") or {}
        vlm_line = ""
        if vlm.get("status") in ("assessed", "proposed"):
            vlm_line = (
                f"<p>Vision model ({_e(vlm.get('model'))}): {_e(vlm.get('description'))}"
                f" - box {_e(vlm.get('box_status', 'verified by changed pixels'))}</p>"
            )
        sev = _e(f.get("severity"))
        sections.append(
            f"<h3>#{_e(f.get('number'))} {_e(f.get('type'))} - <span class='{sev}'>{sev}</span>,"
            f" evidence confidence {_e(f.get('evidence_confidence'))}</h3>"
            f"<p>{_e(f.get('explanation'))}</p>"
            f"<table><tr>{''.join(cells)}</tr></table>"
            f"<p class='muted'>Review status: {_e(f.get('review_status'))}</p>"
            + (f"<p>Overlapping extracted fields: {fields}</p>" if fields else "")
            + vlm_line
            + (f"<p class='muted'>Confidence basis:</p><ul>{basis}</ul>" if basis else "")
        )
    if len(findings) > MAX_CROPS:
        sections.append(
            f"<p class='muted'>Crops are shown for the first {MAX_CROPS} of {len(findings)} "
            "differences; all of them are listed in the table above and in the JSON export.</p>"
        )
    pages = (payload.get("summary") or {}).get("pages") or []
    page_rows = "".join(
        f"<tr><td>{_e(p.get('test_page'))}</td><td>{_e(p.get('original_page'))}</td>"
        f"<td>{_e(p.get('alignment'))}</td><td>{_e(p.get('page_ssim'))}</td>"
        f"<td>{_e(p.get('text_compared'))}</td></tr>"
        for p in pages
    )
    body = (
        _header(payload, "VERITAS AI - document comparison report")
        + "<h2>Documents</h2>"
        + _documents_table(payload)
        + "<h2>Page alignment</h2><table><tr><th>Test page</th><th>Original page</th>"
        f"<th>Alignment</th><th>Page similarity (SSIM)</th><th>Text compared</th></tr>{page_rows}"
        "</table><h2>Differences</h2>"
        + _findings_table(findings)
        + "<h2>Evidence per difference</h2>"
        + "".join(sections)
        + _limitations(payload)
    )
    return _render(body, archive)
