"""Invariants of the forensic result types and the SSIM implementation."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from app.models.forensics import MANDATORY_LIMITATION
from app.services.forensics.imaging import ssim
from app.services.forensics.model import Anomaly, ForensicReport, overlaps

images = arrays(np.uint8, (24, 24), elements=st.integers(0, 255))


@settings(max_examples=40, deadline=None)
@given(images)
def test_ssim_of_an_image_with_itself_is_one(img: np.ndarray) -> None:
    assert ssim(img, img) == pytest.approx(1.0, abs=1e-9)


@settings(max_examples=40, deadline=None)
@given(images, images)
def test_ssim_is_symmetric_and_bounded(a: np.ndarray, b: np.ndarray) -> None:
    value = ssim(a, b)
    assert -1.0 <= value <= 1.0
    assert value == pytest.approx(ssim(b, a), abs=1e-9)


@given(st.lists(st.text(max_size=40), max_size=4), st.sampled_from(["succeeded", "partial"]))
def test_every_report_states_the_mandatory_limitation(extra: list[str], status: str) -> None:
    report = ForensicReport([], {}, {}, [], list(extra), status)
    assert report.limitations.count(MANDATORY_LIMITATION) >= 1
    assert report.limitations[0] == MANDATORY_LIMITATION or MANDATORY_LIMITATION in extra


@given(st.sampled_from(["high", "critical", "forged", ""]))
def test_a_forensic_indicator_never_ranks_above_medium(severity: str) -> None:
    with pytest.raises(ValueError, match="not allowed"):
        Anomaly("font_inconsistency", severity, "x")


boxes = st.tuples(*(st.floats(0, 500) for _ in range(4))).map(
    lambda t: (min(t[0], t[2]), min(t[1], t[3]), max(t[0], t[2]) + 1, max(t[1], t[3]) + 1)
)


@given(boxes, boxes)
def test_overlap_is_symmetric(a: tuple[float, ...], b: tuple[float, ...]) -> None:
    assert overlaps(a, b) == overlaps(b, a)
    assert overlaps(a, a)
