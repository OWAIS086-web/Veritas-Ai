"""PDF text layer extraction (PyMuPDF) and page rendering for OCR."""

from __future__ import annotations

import numpy as np
import pymupdf

from app.services.parsing.model import ParsedPage, Token, assemble_lines

MIN_TEXT_CHARS = 20  # below this a page is treated as having no usable text layer


class PdfError(Exception):
    pass


def open_pdf(data: bytes) -> pymupdf.Document:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except (RuntimeError, ValueError) as exc:
        raise PdfError(f"unreadable PDF: {exc}") from exc
    if doc.needs_pass:
        doc.close()
        raise PdfError("encrypted PDF")
    return doc


def page_count(data: bytes) -> int:
    with open_pdf(data) as doc:
        return len(doc)


def has_text_layer(page: pymupdf.Page) -> bool:
    return len(page.get_text("text").strip()) >= MIN_TEXT_CHARS


def parse_text_page(page: pymupdf.Page, page_number: int) -> ParsedPage:
    """Words with exact boxes in PDF points (top-left origin), grouped into visual lines."""
    tokens = [
        Token(text=w[4], bbox=(w[0], w[1], w[2], w[3]), confidence=1.0)
        for w in page.get_text("words", sort=True)
    ]
    return ParsedPage(
        page_number=page_number,
        width=page.rect.width,
        height=page.rect.height,
        coord_unit="pt",
        method="text_layer",
        lines=assemble_lines(tokens),
    )


def render_page(page: pymupdf.Page, dpi: int) -> np.ndarray:
    """RGB image of a page for OCR."""
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3).copy()
