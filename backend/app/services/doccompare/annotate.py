"""Annotated copies of the test document: a PDF with numbered rectangle annotations and a ZIP
of PNG pages with the same marks drawn in.

Both are new files built from the stored test document's bytes; the stored original is never
written to. Every region is validated against the real page size again before it is drawn, and
a region that doesn't fit is skipped and counted, never stretched onto the page.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

import cv2
import numpy as np
import pymupdf

from app.services.doccompare.geometry import Box, clip, valid
from app.services.doccompare.pages import PDF, page_sizes, rasters

# Severity colours (RGB 0-1) shared by the PDF and the PNG marks.
COLOURS = {
    "medium": (0.80, 0.15, 0.15),
    "low": (0.85, 0.55, 0.05),
    "info": (0.25, 0.45, 0.75),
}
BORDER = 1.5  # rectangle line width, points


@dataclass(frozen=True)
class Mark:
    number: int
    page: int
    region: Box  # test page units, top-left origin
    severity: str
    label: str  # short text for the annotation popup


@dataclass
class DrawStats:
    drawn: int = 0
    skipped: int = 0


def _page_marks(marks: list[Mark], page: int) -> list[Mark]:
    return [m for m in marks if m.page == page]


def _annotate_page(page: pymupdf.Page, marks: list[Mark], stats: DrawStats) -> None:
    width, height = page.rect.width, page.rect.height
    for m in marks:
        # PyMuPDF widens an annotation's rectangle by about its border width; the region is
        # inset by that much at the page edges so the whole annotation stays on the page.
        inner = (
            clip([v - BORDER for v in m.region], width - 2 * BORDER, height - 2 * BORDER)
            if valid(m.region)
            else None
        )
        if inner is None:
            stats.skipped += 1
            continue
        region = [v + BORDER for v in inner]
        colour = COLOURS.get(m.severity, COLOURS["info"])
        # Regions are in the page's displayed (rotated) frame; annotations use the unrotated one.
        rect = pymupdf.Rect(*region) * page.derotation_matrix
        rect.normalize()
        annot = page.add_rect_annot(rect)
        annot.set_colors(stroke=colour)
        annot.set_border(width=BORDER)
        annot.set_info(title=f"VERITAS difference #{m.number}", content=m.label[:900])
        annot.update(opacity=0.9)
        tag_w, tag_h = 26.0, 11.0
        tx0 = min(max(0.0, region[0]), max(0.0, width - tag_w))
        ty0 = region[1] - tag_h if region[1] >= tag_h else min(region[3], height - tag_h)
        tag = pymupdf.Rect(tx0, ty0, tx0 + tag_w, ty0 + tag_h) * page.derotation_matrix
        tag.normalize()
        label = page.add_freetext_annot(
            tag,
            f"#{m.number}",
            fontsize=7,
            text_color=(1, 1, 1),
            fill_color=colour,
            rotate=page.rotation,
        )
        # A free-text annotation shows its content, so it keeps only the number; the
        # explanation is on the rectangle's popup.
        label.set_info(title=f"VERITAS difference #{m.number}")
        label.update(text_color=(1, 1, 1), fill_color=colour)
        stats.drawn += 1


def annotated_pdf(
    data: bytes, mime: str, marks: list[Mark], summary_pdf: bytes | None, dpi: int, max_pages: int
) -> tuple[bytes, DrawStats]:
    """A PDF copy of the test document with the marks; image files become PDF pages first.
    `summary_pdf` (the findings list) is appended after the document's pages."""
    stats = DrawStats()
    if mime == PDF:
        doc = pymupdf.open(stream=bytes(data), filetype="pdf")
    else:
        doc = pymupdf.open()
        for r in rasters(data, mime, dpi, max_pages):
            h, w = r.rgb.shape[:2]
            ok, png = cv2.imencode(".png", cv2.cvtColor(r.rgb, cv2.COLOR_RGB2BGR))
            if not ok:
                raise ValueError("could not encode a page image")
            page = doc.new_page(width=w, height=h)  # image pages: 1 unit per pixel
            page.insert_image(page.rect, stream=png.tobytes())
    try:
        for index in range(len(doc)):
            _annotate_page(doc[index], _page_marks(marks, index + 1), stats)
        stats.skipped += sum(1 for m in marks if m.page > len(doc) or m.page < 1)
        if summary_pdf:
            with pymupdf.open(stream=summary_pdf, filetype="pdf") as extra:
                doc.insert_pdf(extra)
        doc.set_metadata(
            {**(doc.metadata or {}), "producer": "VERITAS AI comparison lab (annotated copy)"}
        )
        return doc.tobytes(garbage=3, deflate=True), stats
    finally:
        doc.close()


def _draw(
    rgb: np.ndarray,
    marks: list[Mark],
    scale: float,
    offset: tuple[float, float],
    page_w: float,
    page_h: float,
    stats: DrawStats,
) -> np.ndarray:
    img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    h, w = img.shape[:2]
    thick = max(2, round(w / 600))
    for m in marks:
        region = clip(m.region, page_w, page_h) if valid(m.region) else None
        if region is None:
            stats.skipped += 1
            continue
        ox, oy = offset
        x0, y0 = int((region[0] - ox) / scale), int((region[1] - oy) / scale)
        x1, y1 = int(np.ceil((region[2] - ox) / scale)), int(np.ceil((region[3] - oy) / scale))
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w - 1, x1), min(h - 1, y1)
        if x1 <= x0 or y1 <= y0:
            stats.skipped += 1
            continue
        r, g, b = COLOURS.get(m.severity, COLOURS["info"])
        colour = (int(b * 255), int(g * 255), int(r * 255))
        cv2.rectangle(img, (x0, y0), (x1, y1), colour, thick)
        text = f"#{m.number}"
        size = max(0.5, w / 1600)
        (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, size, thick)
        ty = y0 - 4 if y0 - th - base - 4 > 0 else min(h - 1, y1 + th + 4)
        cv2.rectangle(img, (x0, ty - th - base), (min(w - 1, x0 + tw + 6), ty + base), colour, -1)
        cv2.putText(
            img,
            text,
            (x0 + 3, ty),
            cv2.FONT_HERSHEY_SIMPLEX,
            size,
            (255, 255, 255),
            thick,
            cv2.LINE_AA,
        )
        stats.drawn += 1
    ok, png = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("could not encode a page image")
    return np.asarray(png)


def annotated_images(
    data: bytes, mime: str, marks: list[Mark], notes: str, dpi: int, max_pages: int
) -> tuple[bytes, DrawStats]:
    """A ZIP of PNG pages of the test document with the marks drawn on them."""
    stats = DrawStats()
    rs = rasters(data, mime, dpi, max_pages)
    sizes = page_sizes(data, mime, rs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r, (pw, ph) in zip(rs, sizes, strict=True):
            png = _draw(r.rgb, _page_marks(marks, r.page_number), r.scale, r.offset, pw, ph, stats)
            zf.writestr(f"test-page-{r.page_number:03d}-annotated.png", png.tobytes())
        stats.skipped += sum(1 for m in marks if m.page > len(rs) or m.page < 1)
        zf.writestr("README.txt", notes)
    return buf.getvalue(), stats
