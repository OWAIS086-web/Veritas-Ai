"""Page registration: the transform that puts the original page on top of the test page.

Three candidates are tried and the one with the best structural similarity wins: identity,
ECC (euclidean: shift and rotation, for scans and re-saved PDFs) and ORB features with a RANSAC
homography (perspective, for photographed pages). The result is `M`, a 3x3 matrix mapping
test work pixels to original work pixels.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.services.forensics.imaging import ssim

ECC_CRITERIA = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6)


@dataclass(frozen=True)
class Registration:
    matrix: np.ndarray  # 3x3, test work px -> original work px
    method: str  # identity | ecc | orb_homography
    ssim: float  # page similarity after alignment


def warp_to_test(
    original: np.ndarray, m: np.ndarray, size: tuple[int, int], fill: int = 255
) -> np.ndarray:
    """The original image resampled into the test frame (`size` is (width, height))."""
    flags = cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP
    if original.ndim == 3:
        border: tuple[float, ...] = (float(fill),) * 3
    else:
        border = (float(fill),)
    return np.asarray(
        cv2.warpPerspective(original, m.astype(np.float64), size, flags=flags, borderValue=border),
        dtype=np.uint8,
    )


def _full_mask(img: np.ndarray) -> np.ndarray:
    """An all-pixels mask (the same as no mask, in the form the OpenCV stubs accept)."""
    return np.full(img.shape[:2], 255, dtype=np.uint8)


def _ecc(test: np.ndarray, original: np.ndarray) -> np.ndarray | None:
    warp = np.eye(2, 3, dtype=np.float32)
    try:
        # Coarse-to-fine: estimate at half size first, so larger shifts still converge.
        small_t = cv2.resize(test, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        small_o = cv2.resize(
            original, (small_t.shape[1], small_t.shape[0]), interpolation=cv2.INTER_AREA
        )
        _, coarse = cv2.findTransformECC(
            small_t.astype(np.float32),
            small_o.astype(np.float32),
            warp,
            cv2.MOTION_EUCLIDEAN,
            ECC_CRITERIA,
            _full_mask(small_t),
            5,
        )
        warp = np.asarray(coarse, dtype=np.float32)
        warp[:, 2] *= 2.0
        _, fine = cv2.findTransformECC(
            test.astype(np.float32),
            original.astype(np.float32),
            warp,
            cv2.MOTION_EUCLIDEAN,
            ECC_CRITERIA,
            _full_mask(test),
            5,
        )
    except cv2.error:
        return None
    return np.vstack([np.asarray(fine, dtype=np.float64), [0.0, 0.0, 1.0]])


def _orb(test: np.ndarray, original: np.ndarray) -> np.ndarray | None:
    orb = cv2.ORB.create(3000)
    k1, d1 = orb.detectAndCompute(test, _full_mask(test))
    k2, d2 = orb.detectAndCompute(original, _full_mask(original))
    if d1 is None or d2 is None or len(k1) < 12 or len(k2) < 12:
        return None
    matches = sorted(
        cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2), key=lambda m: m.distance
    )[:400]
    if len(matches) < 12:
        return None
    src = np.array([k1[m.queryIdx].pt for m in matches], dtype=np.float32).reshape(-1, 1, 2)
    dst = np.array([k2[m.trainIdx].pt for m in matches], dtype=np.float32).reshape(-1, 1, 2)
    h, inliers = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    if h is None or inliers is None or int(inliers.sum()) < 12:
        return None
    return np.asarray(h, dtype=np.float64)  # maps test px -> original px


def register(test: np.ndarray, original: np.ndarray) -> Registration:
    """`test` and `original` are grayscale work images of the same size."""
    size = (test.shape[1], test.shape[0])
    candidates: list[tuple[str, np.ndarray]] = [("identity", np.eye(3))]
    for name, fn in (("ecc", _ecc), ("orb_homography", _orb)):
        m = fn(test, original)
        if m is not None and np.all(np.isfinite(m)):
            candidates.append((name, m))
    best: Registration | None = None
    for name, m in candidates:
        score = ssim(test, warp_to_test(original, m, size))
        # Prefer the simpler transform unless another is clearly better.
        if best is None or score > best.ssim + 0.002:
            best = Registration(m, name, round(score, 4))
    if best is None:  # identity is always a candidate
        raise ValueError("no registration candidate")
    return best
