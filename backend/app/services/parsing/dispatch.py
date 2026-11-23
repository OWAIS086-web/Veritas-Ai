"""Route a document to the right parser by its detected MIME type.

Text-layer PDF pages use PyMuPDF (plus Docling tables); pages without a text layer and image
files go through OpenCV preprocessing and PaddleOCR; office, CSV and email files use direct
parsers. Pure computation: no database access.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings
from app.integrations.ocr.paddle import OcrUnavailableError, engine_version
from app.services.ingestion import detect
from app.services.ocr.service import decode_image, ocr_image
from app.services.parsing import layout, office
from app.services.parsing.model import ParsedPage, detect_language
from app.services.parsing.pdf import has_text_layer, open_pdf, parse_text_page, render_page


class ParseError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class ParseResult:
    pages: list[ParsedPage]
    language: str | None
    ocr_version: str | None
    metrics: dict[str, Any] = field(default_factory=dict)


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def _pdf(data: bytes, metrics: dict[str, Any]) -> tuple[list[ParsedPage], bool]:
    s = get_settings()
    pages: list[ParsedPage] = []
    used_ocr = False
    with open_pdf(data) as doc:
        if len(doc) > s.max_pages:
            raise ParseError(f"too_many_pages:{len(doc)}")
        heights = {}
        for index in range(len(doc)):
            page = doc[index]
            heights[index + 1] = page.rect.height
            if has_text_layer(page):
                pages.append(parse_text_page(page, index + 1))
                continue
            if not s.ocr_enabled:
                raise ParseError("ocr_required_but_disabled")
            start = time.perf_counter()
            rgb = render_page(page, s.ocr_dpi)
            parsed, ocr_metrics = ocr_image(rgb, index + 1, points_per_pixel=72 / s.ocr_dpi)
            metrics.setdefault("ocr_pages", []).append(
                {"page": index + 1, "ms": _ms(start), **ocr_metrics}
            )
            pages.append(parsed)
            used_ocr = True
    text_pages = [p for p in pages if p.method == "text_layer"]
    if text_pages and s.layout_enabled:
        start = time.perf_counter()
        try:
            tables = layout.extract_tables(data, heights, s.layout_timeout_seconds)
            for page in pages:
                if page.method == "text_layer":
                    page.tables = tables.get(page.page_number, [])
            metrics["layout"] = {
                "status": "ok",
                "ms": _ms(start),
                "tables": sum(len(t) for t in tables.values()),
                "engine": layout.layout_version(),
            }
        except (layout.LayoutUnavailableError, TimeoutError) as exc:
            metrics["layout"] = {"status": f"skipped: {exc}", "ms": _ms(start)}
        except Exception as exc:  # layout must never fail the stage
            metrics["layout"] = {"status": f"skipped: {type(exc).__name__}", "ms": _ms(start)}
    return pages, used_ocr


def _images(data: bytes, metrics: dict[str, Any]) -> list[ParsedPage]:
    s = get_settings()
    if not s.ocr_enabled:
        raise ParseError("ocr_required_but_disabled")
    try:
        frames = decode_image(data)
    except ValueError as exc:
        raise ParseError("unreadable_image") from exc
    if len(frames) > s.max_pages:
        raise ParseError(f"too_many_pages:{len(frames)}")
    pages = []
    for index, rgb in enumerate(frames, start=1):
        start = time.perf_counter()
        page, ocr_metrics = ocr_image(rgb, index, points_per_pixel=None)
        metrics.setdefault("ocr_pages", []).append({"page": index, "ms": _ms(start), **ocr_metrics})
        pages.append(page)
    return pages


def parse_document(data: bytes, mime: str) -> ParseResult:
    metrics: dict[str, Any] = {}
    start = time.perf_counter()
    used_ocr = False
    try:
        if mime == detect.PDF:
            pages, used_ocr = _pdf(data, metrics)
        elif mime in (detect.PNG, detect.JPEG, detect.TIFF):
            pages, used_ocr = _images(data, metrics), True
        elif mime == detect.DOCX:
            pages = office.parse_docx(data)
        elif mime == detect.XLSX:
            pages = office.parse_xlsx(data)
        elif mime == detect.CSV:
            pages = office.parse_csv(data)
        elif mime == detect.EML:
            pages, attachments = office.parse_eml(data)
            metrics["attachments_not_processed"] = attachments
        else:
            raise ParseError(f"unsupported_type:{mime}")
    except OcrUnavailableError as exc:
        raise ParseError(f"ocr_unavailable: {exc}") from exc
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"parse_failed: {type(exc).__name__}: {exc}") from exc
    metrics["parse_ms"] = _ms(start)
    metrics["pages"] = len(pages)
    metrics["methods"] = sorted({p.method for p in pages})
    text = "\n".join(p.text for p in pages)
    return ParseResult(
        pages=pages,
        language=detect_language(text),
        ocr_version=engine_version() if used_ocr else None,
        metrics=metrics,
    )
