"""PaddleOCR engine (CPU). Imported lazily: only worker images install the `ocr` extra."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.core.config import get_settings


class OcrUnavailableError(Exception):
    """PaddleOCR is not installed or its models could not be loaded."""


@dataclass(frozen=True)
class OcrLine:
    text: str
    score: float
    polygon: np.ndarray  # (4, 2) points in the input image's pixel coordinates


_engine: Any = None
_lock = threading.Lock()


def engine_version() -> str:
    s = get_settings()
    try:
        import paddleocr

        version = getattr(paddleocr, "__version__", "unknown")
    except ImportError:
        version = "missing"
    return f"paddleocr-{version}/{s.ocr_det_model}+{s.ocr_rec_model}"


def _get_engine() -> Any:
    global _engine
    with _lock:
        if _engine is None:
            os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            try:
                from paddleocr import PaddleOCR
            except ImportError as exc:
                raise OcrUnavailableError("paddleocr is not installed (ocr extra)") from exc
            s = get_settings()
            try:
                _engine = PaddleOCR(
                    text_detection_model_name=s.ocr_det_model,
                    text_recognition_model_name=s.ocr_rec_model,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                    # PaddlePaddle 3.3's oneDNN backend fails on these models on CPU.
                    enable_mkldnn=False,
                )
            except Exception as exc:
                raise OcrUnavailableError(f"could not load OCR models: {exc}") from exc
        return _engine


def recognize(image_bgr: np.ndarray) -> list[OcrLine]:
    engine = _get_engine()
    with _lock:  # the predictor isn't documented as thread-safe
        results = engine.predict(image_bgr)
    lines: list[OcrLine] = []
    for result in results:
        texts = result["rec_texts"]
        scores = result["rec_scores"]
        polys = result["rec_polys"]
        for text, score, poly in zip(texts, scores, polys, strict=True):
            if str(text).strip():
                lines.append(OcrLine(str(text), float(score), np.asarray(poly, dtype=np.float64)))
    return lines
