"""Boxes and the coordinate chain between the two documents.

Every box is [x0, y0, x1, y1] with a top-left origin. A page's units are PDF points, or
pixels for image files (the same as extracted-field boxes). Coordinates flow:

    test page units ⇄ test raster px ⇄ test work px  ⇄(M)⇄  original work px ⇄ original raster
    px ⇄ original page units

`M` (3x3) maps test work px to original work px; it comes from registration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

Box = list[float]
MIN_SIDE = 1.0  # page units; a validated region is at least this wide and high


def valid(box: object) -> bool:
    if not isinstance(box, list | tuple) or len(box) != 4:
        return False
    try:
        x0, y0, x1, y1 = (float(v) for v in box)
    except (TypeError, ValueError):
        return False
    return all(np.isfinite([x0, y0, x1, y1])) and x1 > x0 and y1 > y0


def clip(box: Box, width: float, height: float) -> Box | None:
    """The part of `box` inside the page, or None if too little of it is."""
    x0, y0, x1, y1 = box
    # Rounded to 0.01 inwards, so rounding can never move an edge off the page.
    c = [
        math.ceil(max(0.0, x0) * 100) / 100,
        math.ceil(max(0.0, y0) * 100) / 100,
        math.floor(min(width, x1) * 100) / 100,
        math.floor(min(height, y1) * 100) / 100,
    ]
    if c[2] - c[0] < MIN_SIDE or c[3] - c[1] < MIN_SIDE:
        return None
    return c


def area(b: Box) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def intersection(a: Box, b: Box) -> float:
    return area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def overlaps(a: Box, b: Box) -> bool:
    return intersection(a, b) > 0


def iou(a: Box, b: Box) -> float:
    inter = intersection(a, b)
    union_area = area(a) + area(b) - inter
    return inter / union_area if union_area > 0 else 0.0


def union(boxes: list[Box]) -> Box:
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def expand(b: Box, dx: float, dy: float) -> Box:
    return [b[0] - dx, b[1] - dy, b[2] + dx, b[3] + dy]


def center(b: Box) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def contains_point(b: Box, p: tuple[float, float]) -> bool:
    return b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3]


def transform_box(m: np.ndarray, b: Box) -> Box:
    """Bounding box of the four corners of `b` mapped by the 3x3 matrix `m`."""
    corners = np.array(
        [[b[0], b[1], 1.0], [b[2], b[1], 1.0], [b[2], b[3], 1.0], [b[0], b[3], 1.0]]
    ).T
    mapped = m @ corners
    w = mapped[2]
    w = np.where(np.abs(w) < 1e-9, 1e-9, w)
    xs, ys = mapped[0] / w, mapped[1] / w
    return [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]


@dataclass(frozen=True)
class Frame:
    """One document page: page units ⇄ raster px ⇄ work px (a uniform scale per axis)."""

    page_width: float  # page units
    page_height: float
    unit_per_px: float  # raster px -> page units
    offset: tuple[float, float]  # raster origin on the page, page units
    work_sx: float  # raster px -> work px
    work_sy: float

    def page_to_work(self, b: Box) -> Box:
        ox, oy = self.offset
        u = self.unit_per_px
        return [
            (b[0] - ox) / u * self.work_sx,
            (b[1] - oy) / u * self.work_sy,
            (b[2] - ox) / u * self.work_sx,
            (b[3] - oy) / u * self.work_sy,
        ]

    def work_to_page(self, b: Box) -> Box:
        ox, oy = self.offset
        u = self.unit_per_px
        return [
            ox + b[0] / self.work_sx * u,
            oy + b[1] / self.work_sy * u,
            ox + b[2] / self.work_sx * u,
            oy + b[3] / self.work_sy * u,
        ]

    def page_to_raster(self, b: Box) -> Box:
        ox, oy = self.offset
        u = self.unit_per_px
        return [(b[0] - ox) / u, (b[1] - oy) / u, (b[2] - ox) / u, (b[3] - oy) / u]

    def raster_to_page(self, b: Box) -> Box:
        ox, oy = self.offset
        u = self.unit_per_px
        return [ox + b[0] * u, oy + b[1] * u, ox + b[2] * u, oy + b[3] * u]

    def raster_to_work_matrix(self) -> np.ndarray:
        return np.diag([self.work_sx, self.work_sy, 1.0])
