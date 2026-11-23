"""OpenCV preprocessing for OCR: grayscale, light denoise and deskew, with the inverse
transform so OCR coordinates can be mapped back onto the original page."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

MAX_SKEW_DEGREES = 5.0
MIN_CORRECTION_DEGREES = 0.15


@dataclass(frozen=True)
class Preprocessed:
    image: np.ndarray  # 3-channel uint8, what the OCR engine sees
    angle: float  # degrees the original was rotated by to deskew it
    inverse: np.ndarray  # 2x3 affine: processed coords -> original coords


def estimate_skew(gray: np.ndarray) -> float:
    """Angle (degrees) that maximizes horizontal text-line sharpness (projection profile)."""
    scale = 1000.0 / max(gray.shape)
    small = cv2.resize(
        gray, None, fx=min(1.0, scale), fy=min(1.0, scale), interpolation=cv2.INTER_AREA
    )
    _, binary = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    h, w = binary.shape
    center = (w / 2, h / 2)

    def score(angle: float) -> float:
        m = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(binary, m, (w, h), flags=cv2.INTER_NEAREST, borderValue=(0,))
        profile = rotated.sum(axis=1, dtype=np.float64)
        return float(np.var(profile))

    if not binary.any():
        return 0.0  # blank page: nothing to align
    baseline = score(0.0)
    coarse = max(np.arange(-MAX_SKEW_DEGREES, MAX_SKEW_DEGREES + 0.01, 0.5), key=score)
    fine = max(np.arange(coarse - 0.5, coarse + 0.51, 0.05), key=score)
    # Only rotate when an angle is clearly sharper than the page as it is; flat profiles
    # (blank or uniform pages) would otherwise pick an arbitrary extreme angle.
    if score(float(fine)) <= baseline * 1.02:
        return 0.0
    return round(float(fine), 2)


def preprocess(rgb: np.ndarray) -> Preprocessed:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY) if rgb.ndim == 3 else rgb
    gray = cv2.medianBlur(gray, 3)
    angle = estimate_skew(gray)
    h, w = gray.shape
    if abs(angle) < MIN_CORRECTION_DEGREES:
        angle = 0.0
        forward = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        out = gray
    else:
        forward = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        out = cv2.warpAffine(
            gray, forward, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
        )
    inverse = cv2.invertAffineTransform(forward)
    return Preprocessed(image=cv2.cvtColor(out, cv2.COLOR_GRAY2BGR), angle=angle, inverse=inverse)


def map_points(points: np.ndarray, affine: np.ndarray) -> np.ndarray:
    """Apply a 2x3 affine transform to an (N, 2) array of points."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    mapped: np.ndarray = pts @ affine[:, :2].T + affine[:, 2]
    return mapped
