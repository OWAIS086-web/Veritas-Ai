"""Page rasters and image similarity for the visual analyses.

SSIM follows Wang et al. (2004): Gaussian window (sigma 1.5), K1 0.01, K2 0.03, dynamic range
255. It is implemented with OpenCV here, so no extra image library is needed.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import pymupdf

from app.services.ocr.service import decode_image

C1 = (0.01 * 255) ** 2
C2 = (0.03 * 255) ** 2


@dataclass
class Raster:
    page_number: int
    rgb: np.ndarray  # H x W x 3, uint8
    scale: float  # page units per pixel (PDF points, or 1.0 for image files)
    source: str  # rendered | embedded_image | image_file
    offset: tuple[float, float] = (0.0, 0.0)  # where the raster's origin sits on the page

    @property
    def gray(self) -> np.ndarray:
        return cv2.cvtColor(self.rgb, cv2.COLOR_RGB2GRAY)

    def to_page(self, box_px: tuple[int, int, int, int] | list[int]) -> list[float]:
        x0, y0, x1, y1 = box_px
        ox, oy = self.offset
        return [
            round(ox + x0 * self.scale, 2),
            round(oy + y0 * self.scale, 2),
            round(ox + x1 * self.scale, 2),
            round(oy + y1 * self.scale, 2),
        ]


def _pixmap_rgb(pix: pymupdf.Pixmap) -> np.ndarray:
    if pix.n - pix.alpha != 3:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3).copy()


def pdf_rasters(data: bytes, dpi: int, max_pages: int) -> list[Raster]:
    """One raster per page. A page that is a single full-page image (a scan) is analysed at
    the image's own resolution, so compression artefacts aren't blurred by resampling."""
    out: list[Raster] = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for index in range(min(len(doc), max_pages)):
            page = doc[index]
            images = page.get_images(full=True)
            if len(images) == 1 and not page.get_text("text").strip():
                xref = images[0][0]
                rects = page.get_image_rects(xref)
                if (
                    rects
                    and rects[0].width * rects[0].height >= 0.8 * page.rect.width * page.rect.height
                ):
                    rgb = _pixmap_rgb(pymupdf.Pixmap(doc, xref))
                    rect = rects[0]
                    out.append(
                        Raster(
                            index + 1,
                            rgb,
                            rect.width / rgb.shape[1],
                            "embedded_image",
                            offset=(rect.x0, rect.y0),
                        )
                    )
                    continue
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
            out.append(Raster(index + 1, _pixmap_rgb(pix), 72.0 / dpi, "rendered"))
    return out


def image_rasters(data: bytes, max_pages: int) -> list[Raster]:
    return [
        Raster(i + 1, rgb, 1.0, "image_file")
        for i, rgb in enumerate(decode_image(data)[:max_pages])
    ]


def ssim_map(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Per-pixel SSIM of two equally sized grayscale images, in [-1, 1]."""
    if a.shape != b.shape:
        raise ValueError("images must have the same shape")
    x, y = a.astype(np.float64), b.astype(np.float64)

    def blur(img: np.ndarray) -> np.ndarray:
        return np.asarray(cv2.GaussianBlur(img, (11, 11), 1.5), dtype=np.float64)

    mx, my = blur(x), blur(y)
    vx = blur(x * x) - mx * mx
    vy = blur(y * y) - my * my
    cxy = blur(x * y) - mx * my
    num = (2 * mx * my + C1) * (2 * cxy + C2)
    den = (mx * mx + my * my + C1) * (vx + vy + C2)
    return np.asarray(np.clip(num / den, -1.0, 1.0), dtype=np.float64)


def ssim(a: np.ndarray, b: np.ndarray) -> float:
    return float(ssim_map(a, b).mean())
