"""Docling table extraction for text-layer PDFs (optional `layout` extra).

Docling's own OCR is disabled (PaddleOCR handles scans). Tables are recorded per page with a
top-left-origin bbox in PDF points. Failures and timeouts skip tables; they never fail the stage.
"""

from __future__ import annotations

import concurrent.futures
import io
import threading
from typing import Any

_converter: Any = None
_lock = threading.Lock()
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="docling")


class LayoutUnavailableError(Exception):
    pass


def layout_version() -> str:
    try:
        from importlib.metadata import version

        return f"docling-{version('docling')}"
    except Exception:
        return "docling-missing"


def _get_converter() -> Any:
    global _converter
    with _lock:
        if _converter is None:
            try:
                from docling.datamodel.base_models import InputFormat
                from docling.datamodel.pipeline_options import PdfPipelineOptions
                from docling.document_converter import DocumentConverter, PdfFormatOption
            except ImportError as exc:
                raise LayoutUnavailableError("docling is not installed (layout extra)") from exc
            options = PdfPipelineOptions(do_ocr=False, do_table_structure=True)
            _converter = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
            )
        return _converter


def _extract(data: bytes, page_heights: dict[int, float]) -> dict[int, list[dict[str, Any]]]:
    from docling.datamodel.base_models import DocumentStream

    converter = _get_converter()
    result = converter.convert(DocumentStream(name="document.pdf", stream=io.BytesIO(data)))
    doc = result.document
    tables: dict[int, list[dict[str, Any]]] = {}
    for table in doc.tables:
        frame = table.export_to_dataframe(doc=doc)
        rows = [[str(c) for c in frame.columns]] + [[str(v) for v in r] for r in frame.values]
        prov = table.prov[0] if table.prov else None
        bbox = None
        page_no = prov.page_no if prov else 1
        if prov is not None:
            height = page_heights.get(page_no)
            box = prov.bbox.to_top_left_origin(page_height=height) if height else prov.bbox
            bbox = [round(box.l, 2), round(box.t, 2), round(box.r, 2), round(box.b, 2)]
        tables.setdefault(page_no, []).append({"bbox": bbox, "rows": rows, "source": "docling"})
    return tables


def extract_tables(
    data: bytes, page_heights: dict[int, float], timeout_seconds: float
) -> dict[int, list[dict[str, Any]]]:
    future = _pool.submit(_extract, data, page_heights)
    try:
        return future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError as exc:
        raise TimeoutError(f"docling exceeded {timeout_seconds}s") from exc
