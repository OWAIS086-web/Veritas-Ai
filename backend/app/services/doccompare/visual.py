"""Pixel-level differences between the registered original and the test page.

A pixel counts as changed when local structural similarity is low and the gray levels differ
clearly. Changed pixels are joined into regions; tiny regions, regions on the warp border and
regions whose changed pixels still look structurally similar are noise (changed glyphs on the
forensic invoice fixture score 0.18 at their changed pixels; anti-aliasing and scan noise sit
just under the 0.6 pixel threshold).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.services.doccompare.geometry import Box, clip
from app.services.doccompare.pages import PagePair
from app.services.forensics.imaging import ssim_map

GRAY_DIFF = 40
MIN_AREA = 30  # changed pixels at the work width (about two digits)
REGION_SSIM_MAX = 0.45
BORDER = 0.02


@dataclass(frozen=True)
class VisualRegion:
    test_page: int
    work_box: Box  # test work px
    region: Box  # test page units (validated)
    original_region: Box | None  # original page units (validated), None if outside the page
    local_ssim: float
    changed_pixels: int


def changed_mask(pair: PagePair, threshold: float) -> tuple[np.ndarray, np.ndarray]:
    """(changed pixels, SSIM map) in the test work frame; warp border pixels never count."""
    smap = ssim_map(pair.test_work, pair.original_aligned)
    diff = np.abs(pair.test_work.astype(np.int16) - pair.original_aligned.astype(np.int16))
    changed = (smap < threshold) & (diff > GRAY_DIFF) & pair.valid_mask
    return changed, smap


def detect(pair: PagePair, threshold: float) -> tuple[list[VisualRegion], np.ndarray]:
    changed, smap = changed_mask(pair, threshold)
    closed = np.asarray(
        cv2.morphologyEx(changed.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)),
        dtype=np.uint8,
    )
    count, _, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    height, width = changed.shape
    mx, my = BORDER * width, BORDER * height
    out: list[VisualRegion] = []
    for x, y, w, h, _area in stats[1:count]:
        window = changed[y : y + h, x : x + w]
        pixels = int(window.sum())
        if pixels < MIN_AREA:
            continue
        if x < mx or y < my or x + w > width - mx or y + h > height - my:
            continue
        # Similarity at the changed pixels themselves: a small edit inside a mostly blank box
        # would otherwise be averaged away by the unchanged background.
        local = float(smap[y : y + h, x : x + w][window].mean())
        if local > REGION_SSIM_MAX:
            continue
        work_box = [float(x), float(y), float(x + w), float(y + h)]
        region = clip(
            pair.test_work_box_to_page(work_box),
            pair.test_frame.page_width,
            pair.test_frame.page_height,
        )
        if region is None:
            continue
        original = clip(
            pair.test_box_to_original(region),
            pair.original_frame.page_width,
            pair.original_frame.page_height,
        )
        out.append(
            VisualRegion(pair.test_page, work_box, region, original, round(local, 3), pixels)
        )
    return out, changed


def changed_fraction(changed: np.ndarray, work_box: Box) -> tuple[int, float, Box | None]:
    """Changed pixels inside a work-frame box: count, share, and their tight bounding box."""
    h, w = changed.shape
    x0, y0 = max(0, int(work_box[0])), max(0, int(work_box[1]))
    x1, y1 = min(w, int(np.ceil(work_box[2]))), min(h, int(np.ceil(work_box[3])))
    if x1 <= x0 or y1 <= y0:
        return 0, 0.0, None
    window = changed[y0:y1, x0:x1]
    count = int(window.sum())
    if count == 0:
        return 0, 0.0, None
    ys, xs = np.nonzero(window)
    tight = [
        float(x0 + xs.min()),
        float(y0 + ys.min()),
        float(x0 + xs.max() + 1),
        float(y0 + ys.max() + 1),
    ]
    return count, count / window.size, tight
