"""Download and load the OCR and layout models once (run at worker start).

Failure is reported but not fatal: documents that need OCR or tables then record the
problem in their stage metrics instead of failing silently.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    from app.integrations.ocr import paddle
    from app.services.parsing import layout

    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((20, 40), "WARM UP 12345", fontsize=14)
    data = doc.tobytes()
    import numpy as np

    pix = page.get_pixmap(dpi=100)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3]
    status = 0
    start = time.perf_counter()
    try:
        lines = paddle.recognize(np.ascontiguousarray(image[:, :, ::-1]))
        print(
            f"ocr ready ({paddle.engine_version()}): {[ln.text for ln in lines]} "
            f"in {time.perf_counter() - start:.1f}s",
            flush=True,
        )
    except Exception as exc:
        print(f"ocr NOT ready: {exc}", flush=True)
        status = 1
    start = time.perf_counter()
    try:
        layout.extract_tables(data, {1: 200.0}, timeout_seconds=900)
        print(
            f"layout ready ({layout.layout_version()}) in {time.perf_counter() - start:.1f}s",
            flush=True,
        )
    except Exception as exc:
        print(f"layout NOT ready: {exc}", flush=True)
        status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
