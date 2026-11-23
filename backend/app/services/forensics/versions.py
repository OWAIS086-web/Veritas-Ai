"""Compare a document with the version it supersedes: align each page, then report the
regions whose structural similarity (SSIM) is low."""

from __future__ import annotations

import cv2
import numpy as np

from app.services.forensics.imaging import Raster, ssim_map
from app.services.forensics.model import AnalysisResult, Anomaly, FieldBox, overlapping_fields

ANALYSIS = "version_comparison"
WORK_WIDTH = 1000  # pixels; pages are compared at this width
MIN_AREA = 30  # pixels at the working width (about two digits); smaller is rendering noise
# Measured on the fixtures: changed content scores about 0.2 here, while scan noise and
# anti-aliasing between a vector page and its scan stay above 0.55.
REGION_SSIM_MAX = 0.45
BORDER = 0.02  # regions touching this margin come from the alignment warp, not the content


def _resize(gray: np.ndarray, width: int) -> np.ndarray:
    h = round(gray.shape[0] * width / gray.shape[1])
    return cv2.resize(gray, (width, h), interpolation=cv2.INTER_AREA)


def align(reference: np.ndarray, moving: np.ndarray) -> tuple[np.ndarray, str]:
    """Warp `moving` onto `reference`: ECC (euclidean), then ORB + RANSAC homography if ECC
    doesn't converge, else unaligned."""
    size = (reference.shape[1], reference.shape[0])
    moving = np.asarray(cv2.resize(moving, size), dtype=np.uint8)
    warp = np.eye(2, 3, dtype=np.float32)
    mask = np.full(reference.shape, 255, dtype=np.uint8)
    try:
        _, estimated = cv2.findTransformECC(
            reference.astype(np.float32),
            moving.astype(np.float32),
            warp,
            cv2.MOTION_EUCLIDEAN,
            (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-5),
            mask,
            5,
        )
        aligned = cv2.warpAffine(
            moving,
            np.asarray(estimated, dtype=np.float32),
            size,
            flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
            borderValue=(255.0,),
        )
        return np.asarray(aligned, dtype=np.uint8), "ecc"
    except cv2.error:
        pass
    orb = cv2.ORB.create(2000)
    k1, d1 = orb.detectAndCompute(reference, mask)
    k2, d2 = orb.detectAndCompute(moving, mask)
    if d1 is not None and d2 is not None and len(k1) >= 8 and len(k2) >= 8:
        matches = sorted(
            cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2), key=lambda m: m.distance
        )[:300]
        if len(matches) >= 8:
            src = np.array([k2[m.trainIdx].pt for m in matches], dtype=np.float32).reshape(-1, 1, 2)
            dst = np.array([k1[m.queryIdx].pt for m in matches], dtype=np.float32).reshape(-1, 1, 2)
            h, _ = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
            if h is not None:
                warped = cv2.warpPerspective(
                    moving, np.asarray(h, dtype=np.float64), size, borderValue=(255.0,)
                )
                return np.asarray(warped, dtype=np.uint8), "orb_homography"
    return moving, "none"


def analyze(
    previous: list[Raster], current: list[Raster], fields: list[FieldBox], threshold: float
) -> AnalysisResult:
    result = AnalysisResult(
        ANALYSIS,
        limitations=[
            "Differences between versions are expected when a document is legitimately amended; "
            "they show what changed, not why.",
            "Pages are compared in order; inserted or removed pages shift the comparison.",
        ],
    )
    pages = []
    for old, new in zip(previous, current, strict=False):
        ref = _resize(old.gray, WORK_WIDTH)
        cur, method = align(ref, _resize(new.gray, WORK_WIDTH))
        smap = ssim_map(ref, cur)
        changed = (smap < threshold) & (np.abs(ref.astype(np.int16) - cur.astype(np.int16)) > 40)
        closed = np.asarray(
            cv2.morphologyEx(changed.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)),
            dtype=np.uint8,
        )
        count, _, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
        score = float(smap.mean())
        to_new = new.rgb.shape[1] / WORK_WIDTH  # working pixels -> pixels of the new raster
        regions = 0
        height, width = ref.shape
        mx, my = BORDER * width, BORDER * height
        for x, y, w, h, area in stats[1:count]:
            if area < MIN_AREA:
                continue
            if x < mx or y < my or x + w > width - mx or y + h > height - my:
                continue
            local = float(smap[y : y + h, x : x + w].mean())
            if local > REGION_SSIM_MAX:
                continue
            regions += 1
            px = [int(x * to_new), int(y * to_new), int((x + w) * to_new), int((y + h) * to_new)]
            region = new.to_page(px)
            hits = overlapping_fields(fields, new.page_number, region)
            names = sorted({h_.name.replace("_", " ") for h_ in hits})
            result.anomalies.append(
                Anomaly(
                    "version_difference",
                    "medium" if hits else "low",
                    f"Page {new.page_number} differs from the previous version in this region "
                    f"(local SSIM {local:.2f}, page SSIM {score:.3f})."
                    + (f" It overlaps the extracted {', '.join(names)}." if hits else ""),
                    page_number=new.page_number,
                    region=region,
                    metrics={
                        "local_ssim": round(local, 3),
                        "page_ssim": round(score, 4),
                        "alignment": method,
                        "threshold": threshold,
                        "fields": [h_.field_id for h_ in hits],
                    },
                )
            )
        pages.append(
            {
                "page": new.page_number,
                "ssim": round(score, 4),
                "alignment": method,
                "regions": regions,
            }
        )
    if len(previous) != len(current):
        result.anomalies.append(
            Anomaly(
                "version_difference",
                "low",
                f"The page count changed from {len(previous)} to {len(current)}.",
                metrics={"previous_pages": len(previous), "pages": len(current)},
            )
        )
    result.details = {"pages": pages, "threshold": threshold}
    return result
