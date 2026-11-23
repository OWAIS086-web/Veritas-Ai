"""Candidate stamp and signature regions, and the comparison of repeated stamps.

Coloured ink is found with an HSV saturation mask, closed morphologically and split into
contours. Round-ish dense contours are stamp candidates; wide, sparse strokes are signature
candidates. These are locations for a reviewer to look at. Nothing here judges whether a
signature or a stamp is genuine.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from app.services.forensics.imaging import Raster, ssim
from app.services.forensics.model import AnalysisResult, Anomaly

ANALYSIS = "stamps_signatures"
DESCRIPTOR = 192  # stamp crops are compared as 192x192 binary ink masks
INK_TOLERANCE_PX = 1  # ink within this distance in the other stamp counts as matched
MIN_STAMP_PX = 60
STAMP_FILL = (0.04, 0.6)  # share of the bounding box covered by ink
SIGNATURE_FILL_MAX = 0.35
SIZE_TOLERANCE = 0.25  # two stamps are "the same stamp" candidates within this size ratio
HUE_TOLERANCE = 12  # OpenCV hue units (0-180)


@dataclass
class InkRegion:
    kind: str  # stamp | signature
    page_number: int
    box_px: tuple[int, int, int, int]
    region: list[float]
    hue: float
    fill: float
    descriptor: np.ndarray | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind,
            "page": self.page_number,
            "region": self.region,
            "hue": round(self.hue, 1),
            "fill": round(self.fill, 3),
        }
        if self.descriptor is not None:
            ok, png = cv2.imencode(".png", self.descriptor)
            if ok:
                out["descriptor"] = base64.b64encode(png.tobytes()).decode()
        return out


def ink_mask(rgb: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    return ((hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 50)).astype(np.uint8) * 255


def _descriptor(mask: np.ndarray) -> np.ndarray:
    small = cv2.resize(mask, (DESCRIPTOR, DESCRIPTOR), interpolation=cv2.INTER_AREA)
    return ((small > 100) * 255).astype(np.uint8)


def unmatched_ink(a: np.ndarray, b: np.ndarray, tolerance: int = INK_TOLERANCE_PX) -> float:
    """Share of the ink in two stamp masks that has no ink of the other stamp within
    `tolerance` pixels. 0 means identical shapes; it is symmetric and in [0, 1]."""
    x, y = (a > 0).astype(np.uint8), (b > 0).astype(np.uint8)
    kernel = np.ones((2 * tolerance + 1, 2 * tolerance + 1), np.uint8)
    dx = np.asarray(cv2.dilate(x, kernel), dtype=np.uint8)
    dy = np.asarray(cv2.dilate(y, kernel), dtype=np.uint8)
    total = int(x.sum() + y.sum())
    if total == 0:
        return 0.0
    return float(int((x & (1 - dy)).sum()) + int((y & (1 - dx)).sum())) / total


def find_regions(raster: Raster) -> list[InkRegion]:
    mask = ink_mask(raster.rgb)
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    hsv = cv2.cvtColor(raster.rgb, cv2.COLOR_RGB2HSV)
    page_h, page_w = mask.shape
    out: list[InkRegion] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < 12 or h < 8 or w * h > 0.2 * page_w * page_h:
            continue
        crop = mask[y : y + h, x : x + w]
        fill = float((crop > 0).mean())
        hue = float(np.median(hsv[y : y + h, x : x + w, 0][crop > 0])) if fill else 0.0
        aspect = w / h
        box = (x, y, x + w, y + h)
        if (
            min(w, h) >= MIN_STAMP_PX
            and 0.6 <= aspect <= 1.6
            and STAMP_FILL[0] <= fill <= STAMP_FILL[1]
        ):
            out.append(
                InkRegion(
                    "stamp",
                    raster.page_number,
                    box,
                    raster.to_page(box),
                    hue,
                    fill,
                    _descriptor(crop),
                )
            )
        elif aspect >= 2.0 and fill <= SIGNATURE_FILL_MAX and h >= 12:
            out.append(
                InkRegion("signature", raster.page_number, box, raster.to_page(box), hue, fill)
            )
    return out


def decode_descriptor(value: str) -> np.ndarray | None:
    try:
        data = np.frombuffer(base64.b64decode(value), dtype=np.uint8)
    except ValueError:
        return None
    img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    return img if img is not None and img.shape == (DESCRIPTOR, DESCRIPTOR) else None


def analyze(
    rasters: list[Raster],
    other_stamps: list[dict[str, Any]],
    threshold: float,
) -> AnalysisResult:
    """`other_stamps` are stamps already found on other documents of the same case:
    {"document_id", "filename", "hue", "region", "descriptor"}."""
    result = AnalysisResult(
        ANALYSIS,
        limitations=[
            "Stamp and signature regions are located by ink colour and shape. A black-ink stamp or "
            "signature is not found.",
            "Similarity between stamp images is measured, not authenticity. A different stamp "
            "can be legitimate (another office, a reissued stamp), and a similar one can be "
            "copied.",
            "No statement is made about whether a signature is genuine.",
        ],
    )
    found: list[InkRegion] = []
    for raster in rasters:
        found.extend(find_regions(raster))
    comparisons = []
    for stamp in found:
        mine = stamp.descriptor
        if stamp.kind != "stamp" or mine is None:
            continue
        w0, h0 = stamp.region[2] - stamp.region[0], stamp.region[3] - stamp.region[1]
        for other in other_stamps:
            desc = decode_descriptor(other.get("descriptor", ""))
            if desc is None:
                continue
            ow, oh = (
                other["region"][2] - other["region"][0],
                other["region"][3] - other["region"][1],
            )
            same_size = abs(ow - w0) <= SIZE_TOLERANCE * max(w0, ow) and abs(
                oh - h0
            ) <= SIZE_TOLERANCE * max(h0, oh)
            same_hue = abs(float(other["hue"]) - stamp.hue) <= HUE_TOLERANCE
            if not (same_size and same_hue):
                continue  # a different stamp, not a repeated one
            difference = unmatched_ink(mine, desc)
            comparisons.append(
                {
                    "page": stamp.page_number,
                    "other_document_id": other["document_id"],
                    "other_filename": other.get("filename"),
                    "unmatched_ink": round(difference, 4),
                    "ssim": round(ssim(mine, desc), 3),
                }
            )
            if difference > threshold:
                result.anomalies.append(
                    Anomaly(
                        "stamp_appearance_variation",
                        "medium",
                        f"The stamp on page {stamp.page_number} matches the size and colour of the "
                        f"stamp on {other.get('filename', 'another document')} of this case, but "
                        f"{difference:.1%} of their ink has no counterpart in the other stamp "
                        f"(threshold {threshold:.1%}), for example different lettering.",
                        page_number=stamp.page_number,
                        region=stamp.region,
                        metrics={
                            "unmatched_ink": round(difference, 4),
                            "threshold": threshold,
                            "other_document_id": other["document_id"],
                            "other_region": other["region"],
                        },
                    )
                )
    result.details = {
        "regions": [r.to_json() for r in found],
        "comparisons": comparisons,
        "threshold": threshold,
    }
    return result
