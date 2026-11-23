"""Page preparation: rasters of both documents, page pairing, work images, registration, and
the coordinate frames that map boxes between them."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.services.doccompare.geometry import Box, Frame, transform_box
from app.services.doccompare.registration import Registration, register, warp_to_test
from app.services.forensics.imaging import Raster, image_rasters, pdf_rasters

IMAGE_TYPES = {"image/png", "image/jpeg", "image/tiff"}
PDF = "application/pdf"


class UnsupportedDocumentError(ValueError):
    pass


def rasters(data: bytes, mime: str, dpi: int, max_pages: int) -> list[Raster]:
    if mime == PDF:
        return pdf_rasters(data, dpi, max_pages)
    if mime in IMAGE_TYPES:
        return image_rasters(data, max_pages)
    raise UnsupportedDocumentError(
        f"{mime} can't be compared visually; use PDF or PNG, JPEG or TIFF images"
    )


def page_sizes(data: bytes, mime: str, rs: list[Raster]) -> list[tuple[float, float]]:
    """Each page's size in its own units (points for PDF, pixels for images)."""
    if mime == PDF:
        import pymupdf

        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return [
                (doc[r.page_number - 1].rect.width, doc[r.page_number - 1].rect.height) for r in rs
            ]
    return [(float(r.rgb.shape[1]), float(r.rgb.shape[0])) for r in rs]


@dataclass
class PagePair:
    test_page: int
    original_page: int
    test_raster: Raster
    original_raster: Raster
    test_frame: Frame
    original_frame: Frame
    test_work: np.ndarray  # grayscale, work size
    original_aligned: np.ndarray  # grayscale original warped into the test work frame
    valid_mask: np.ndarray  # True where the warped original has real content (not border fill)
    registration: Registration

    @property
    def work_size(self) -> tuple[int, int]:
        return self.test_work.shape[1], self.test_work.shape[0]

    # Coordinate mapping between the two documents (boxes in page units).
    def test_box_to_original(self, box: Box) -> Box:
        work = self.test_frame.page_to_work(box)
        return self.original_frame.work_to_page(transform_box(self.registration.matrix, work))

    def original_box_to_test(self, box: Box) -> Box:
        work = self.original_frame.page_to_work(box)
        inv = np.linalg.inv(self.registration.matrix)
        return self.test_frame.work_to_page(transform_box(inv, work))

    def test_work_box_to_page(self, box: Box) -> Box:
        return self.test_frame.work_to_page(box)

    def raster_matrix(self) -> np.ndarray:
        """Test raster px -> original raster px."""
        d_t = self.test_frame.raster_to_work_matrix()
        d_o = self.original_frame.raster_to_work_matrix()
        return np.asarray(np.linalg.inv(d_o) @ self.registration.matrix @ d_t, dtype=np.float64)

    def original_rgb_aligned(self) -> np.ndarray:
        """The original page at the test raster's resolution, aligned to it (for crops)."""
        h, w = self.test_raster.rgb.shape[:2]
        return warp_to_test(self.original_raster.rgb, self.raster_matrix(), (w, h))


def _frame(r: Raster, size: tuple[float, float], work_w: int, work_h: int) -> Frame:
    h, w = r.rgb.shape[:2]
    return Frame(
        page_width=size[0],
        page_height=size[1],
        unit_per_px=r.scale,
        offset=r.offset,
        work_sx=work_w / w,
        work_sy=work_h / h,
    )


def pair_pages(
    original: list[Raster],
    original_sizes: list[tuple[float, float]],
    test: list[Raster],
    test_sizes: list[tuple[float, float]],
    work_width: int,
) -> list[PagePair]:
    """Pages are paired in order; extra pages on either side are reported by the caller."""
    pairs: list[PagePair] = []
    for o, osz, t, tsz in zip(original, original_sizes, test, test_sizes, strict=False):
        th, tw = t.rgb.shape[:2]
        work_h = max(1, round(th * work_width / tw))
        test_work = np.asarray(
            cv2.resize(t.gray, (work_width, work_h), interpolation=cv2.INTER_AREA), dtype=np.uint8
        )
        orig_work = np.asarray(
            cv2.resize(o.gray, (work_width, work_h), interpolation=cv2.INTER_AREA), dtype=np.uint8
        )
        reg = register(test_work, orig_work)
        aligned = warp_to_test(orig_work, reg.matrix, (work_width, work_h))
        valid = (
            warp_to_test(np.full_like(orig_work, 255), reg.matrix, (work_width, work_h), fill=0)
            > 128
        )
        pairs.append(
            PagePair(
                test_page=t.page_number,
                original_page=o.page_number,
                test_raster=t,
                original_raster=o,
                test_frame=_frame(t, tsz, work_width, work_h),
                original_frame=_frame(o, osz, work_width, work_h),
                test_work=test_work,
                original_aligned=aligned,
                valid_mask=valid,
                registration=reg,
            )
        )
    return pairs
