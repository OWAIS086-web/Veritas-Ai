"""OCR a page image and return a ParsedPage in the page's own coordinate system."""

from __future__ import annotations

import cv2
import numpy as np

from app.integrations.ocr import paddle
from app.services.ocr.preprocess import map_points, preprocess
from app.services.parsing.model import COLUMN_GAP, ParsedPage, Token, assemble_lines

# Image files keep pixel coordinates. Scanned pages are typically ~200 dpi, where the 14 pt
# label/value gap is about 39 px.
IMAGE_GAP_PX = 39.0


def ocr_image(
    rgb: np.ndarray,
    page_number: int,
    *,
    points_per_pixel: float | None,
) -> tuple[ParsedPage, dict[str, float]]:
    """OCR one page.

    `points_per_pixel`: for rendered PDF pages, 72/dpi so boxes are in PDF points;
    None for image files, whose boxes stay in pixels.
    """
    prepared = preprocess(rgb)
    lines = paddle.recognize(prepared.image)
    scale = points_per_pixel or 1.0
    tokens: list[Token] = []
    for line in lines:
        original = map_points(line.polygon, prepared.inverse) * scale
        x0, y0 = original.min(axis=0)
        x1, y1 = original.max(axis=0)
        tokens.append(
            Token(
                text=line.text,
                bbox=(float(x0), float(y0), float(x1), float(y1)),
                confidence=line.score,
            )
        )
    h, w = rgb.shape[:2]
    gap = COLUMN_GAP if points_per_pixel else IMAGE_GAP_PX
    page = ParsedPage(
        page_number=page_number,
        width=w * scale,
        height=h * scale,
        coord_unit="pt" if points_per_pixel else "px",
        method="ocr",
        lines=assemble_lines(tokens, gap),
    )
    return page, {"deskew_degrees": prepared.angle, "ocr_lines": float(len(lines))}


def decode_image(data: bytes) -> list[np.ndarray]:
    """Decode PNG/JPEG/TIFF (all TIFF pages) into RGB arrays."""
    ok, frames = cv2.imdecodemulti(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if not ok or not frames:
        single = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if single is None:
            raise ValueError("unreadable image")
        frames = [single]
    return [cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in frames]
