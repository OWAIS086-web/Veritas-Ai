"""Localized compression and noise analysis (OpenCV), for raster content.

A scan carries sensor noise across the whole page. A region that was cut out, saved with
stronger JPEG compression and pasted back loses most of that noise. Each raster is divided
into blocks. For each block with mostly flat background, the noise level is estimated as the
MAD of the high-pass residual on low-gradient pixels. A block is an outlier when it is more
than `k` robust standard deviations (median and MAD) from the page median. Adjacent outliers
are merged into one region, which also records its JPEG grid blockiness as a supporting value.

Pages drawn from a vector text layer have no compression to measure and are recorded as not
applicable.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.services.forensics.imaging import Raster
from app.services.forensics.model import AnalysisResult, Anomaly, FieldBox, overlapping_fields

ANALYSIS = "visual_compression"
BLOCK = 32  # pixels
FLAT_GRADIENT = 40.0  # Sobel magnitude below which a pixel counts as background
MIN_FLAT_SHARE = 0.5  # a block is measured when at least half of it is background
MIN_REGION_BLOCKS = 2  # a single deviating block is treated as noise
NOISE_DROP = 0.5  # a flagged block keeps less than half the page's median noise


def noise_map(gray: np.ndarray) -> np.ndarray:
    """Per-block background noise level (NaN where a block is mostly text or graphics)."""
    g = gray.astype(np.float64)
    residual = g - cv2.GaussianBlur(g, (0, 0), 1.0)
    grad = np.hypot(
        cv2.Sobel(g, cv2.CV_64F, 1, 0, ksize=3), cv2.Sobel(g, cv2.CV_64F, 0, 1, ksize=3)
    )
    flat = grad < FLAT_GRADIENT
    rows, cols = gray.shape[0] // BLOCK, gray.shape[1] // BLOCK
    out = np.full((rows, cols), np.nan)
    for r in range(rows):
        for c in range(cols):
            cell = (slice(r * BLOCK, (r + 1) * BLOCK), slice(c * BLOCK, (c + 1) * BLOCK))
            mask = flat[cell]
            if mask.mean() >= MIN_FLAT_SHARE:
                out[r, c] = float(np.median(np.abs(residual[cell][mask]))) * 1.4826
    return out


def blockiness(gray: np.ndarray) -> float:
    """Mean excess jump across 8-pixel JPEG grid lines compared with jumps inside cells."""
    g = gray.astype(np.float64)
    dx, dy = np.abs(np.diff(g, axis=1)), np.abs(np.diff(g, axis=0))
    if dx.shape[1] <= 8 or dy.shape[0] <= 8:
        return 0.0
    on = (dx[:, 7::8].mean() + dy[7::8, :].mean()) / 2
    off = (
        np.delete(dx, np.s_[7::8], axis=1).mean() + np.delete(dy, np.s_[7::8], axis=0).mean()
    ) / 2
    return float(on - off)


def robust_z(values: np.ndarray) -> np.ndarray:
    """(x - median) / (1.4826 · MAD), ignoring NaN; no spread gives zero scores."""
    finite = values[np.isfinite(values)]
    if finite.size < 8:
        return np.zeros_like(values)
    median = float(np.median(finite))
    mad = float(np.median(np.abs(finite - median))) * 1.4826
    if mad < 1e-6:
        return np.zeros_like(values)
    return (values - median) / mad


def _regions(mask: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    return [
        (int(x), int(y), int(x + w), int(y + h), int(area)) for x, y, w, h, area in stats[1:count]
    ]


def analyze(rasters: list[Raster], fields: list[FieldBox], k: float) -> AnalysisResult:
    result = AnalysisResult(
        ANALYSIS,
        limitations=[
            "Scanners, printers and messaging apps also compress and denoise images; a region "
            "with different noise can come from how the copy was made.",
            "Pages drawn from a text layer contain no compressed image content and are not "
            "measured.",
            "Only regions aligned to whole blocks are measured; very small edits may not show.",
        ],
    )
    pages = []
    for raster in rasters:
        if raster.source == "rendered":
            pages.append(
                {"page": raster.page_number, "source": raster.source, "status": "not_applicable"}
            )
            continue
        gray = raster.gray
        noise = noise_map(gray)
        z = robust_z(noise)
        page_median = float(np.nanmedian(noise)) if np.isfinite(noise).any() else None
        # Recompression removes noise, so only the low side counts, and the drop must also
        # be large in absolute terms (a tight spread alone would inflate the z-scores).
        flagged = np.isfinite(noise) & (z < -k) & (noise < NOISE_DROP * (page_median or 0.0))
        pages.append(
            {
                "page": raster.page_number,
                "source": raster.source,
                "status": "measured",
                "measured_blocks": int(np.isfinite(noise).sum()),
                "median_noise": None if page_median is None else round(page_median, 3),
                "page_blockiness": round(blockiness(gray), 3),
                "flagged_blocks": int(flagged.sum()),
            }
        )
        for c0, r0, c1, r1, area in _regions(flagged):
            if area < MIN_REGION_BLOCKS:
                continue
            px = (c0 * BLOCK, r0 * BLOCK, c1 * BLOCK, r1 * BLOCK)
            region = raster.to_page(px)
            cells = (slice(r0, r1), slice(c0, c1))
            region_noise = float(np.nanmedian(np.where(flagged[cells], noise[cells], np.nan)))
            hits = overlapping_fields(fields, raster.page_number, region)
            names = sorted({h.name.replace("_", " ") for h in hits})
            result.anomalies.append(
                Anomaly(
                    "localized_compression_anomaly",
                    "medium" if hits else "low",
                    f"A region on page {raster.page_number} has much less background noise "
                    f"than the rest of the page (more than {k:g} robust deviations below the "
                    "page median), as seen when a region is saved separately with stronger "
                    "compression and pasted back."
                    + (f" It overlaps the extracted {', '.join(names)}." if hits else ""),
                    page_number=raster.page_number,
                    region=region,
                    metrics={
                        "blocks": area,
                        "region_noise": round(region_noise, 3),
                        "page_median_noise": pages[-1]["median_noise"],
                        "min_z": round(float(np.nanmin(z[cells])), 2),
                        "region_blockiness": round(
                            blockiness(gray[px[1] : px[3], px[0] : px[2]]), 3
                        ),
                        "page_blockiness": pages[-1]["page_blockiness"],
                        "k": k,
                        "fields": [h.field_id for h in hits],
                    },
                )
            )
    result.details = {"pages": pages, "block_px": BLOCK, "k": k}
    return result
