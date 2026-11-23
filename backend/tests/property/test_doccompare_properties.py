"""Invariants of the comparison lab: box geometry and coordinate frames, region validation,
evidence confidence and wording, and annotation bounds."""

from __future__ import annotations

import numpy as np
import pymupdf
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.doccompare.annotate import Mark, annotated_pdf
from app.services.doccompare.fusion import Candidate, score
from app.services.doccompare.geometry import Frame, clip, iou, transform_box, valid
from app.services.doccompare.vision import in_image

coord = st.floats(-2000, 2000, allow_nan=False, allow_infinity=False)
boxes = st.lists(coord, min_size=4, max_size=4)
sizes = st.tuples(st.floats(10, 2000), st.floats(10, 2000))
SOURCES = st.sampled_from([["ocr"], ["ocr", "cv"], ["cv"], ["vlm", "cv"], ["page"]])
TYPES = st.sampled_from(
    [
        "text_changed",
        "text_added",
        "text_removed",
        "visual_difference",
        "page_added",
        "page_removed",
        "vlm_observed_difference",
    ]
)


@settings(max_examples=200, deadline=None)
@given(boxes, sizes)
def test_clip_returns_a_valid_box_inside_the_page_or_nothing(
    b: list[float], size: tuple[float, float]
) -> None:
    w, h = size
    out = clip(b, w, h)
    if out is not None:
        assert valid(out)
        assert 0 <= out[0] < out[2] <= w and 0 <= out[1] < out[3] <= h


@settings(max_examples=200, deadline=None)
@given(boxes, boxes)
def test_iou_is_symmetric_and_bounded(a: list[float], b: list[float]) -> None:
    assert 0.0 <= iou(a, b) <= 1.0
    assert iou(a, b) == pytest.approx(iou(b, a))


@settings(max_examples=100, deadline=None)
@given(
    st.floats(0.2, 3.0),
    st.tuples(st.floats(-50, 50), st.floats(-50, 50)),
    st.floats(0.1, 4.0),
    st.floats(0.1, 4.0),
    st.lists(st.floats(0, 500), min_size=4, max_size=4),
)
def test_frame_page_work_round_trip(
    unit: float, offset: tuple[float, float], sx: float, sy: float, raw: list[float]
) -> None:
    box = [
        min(raw[0], raw[2]),
        min(raw[1], raw[3]),
        max(raw[0], raw[2]) + 1,
        max(raw[1], raw[3]) + 1,
    ]
    f = Frame(600, 900, unit, offset, sx, sy)
    assert f.work_to_page(f.page_to_work(box)) == pytest.approx(box, abs=1e-6)
    assert f.raster_to_page(f.page_to_raster(box)) == pytest.approx(box, abs=1e-6)


@settings(max_examples=100, deadline=None)
@given(
    st.lists(st.floats(0, 500), min_size=4, max_size=4), st.floats(-0.1, 0.1), st.floats(-40, 40)
)
def test_transform_box_inverse_returns_a_box_containing_the_original(
    raw: list[float], angle: float, shift: float
) -> None:
    box = [
        min(raw[0], raw[2]),
        min(raw[1], raw[3]),
        max(raw[0], raw[2]) + 1,
        max(raw[1], raw[3]) + 1,
    ]
    c, s = np.cos(angle), np.sin(angle)
    m = np.array([[c, -s, shift], [s, c, -shift], [0, 0, 1.0]])
    back = transform_box(np.linalg.inv(m), transform_box(m, box))
    # Bounding boxes of rotated boxes only grow; they always contain the source box.
    assert back[0] <= box[0] + 1e-6 and back[1] <= box[1] + 1e-6
    assert back[2] >= box[2] - 1e-6 and back[3] >= box[3] - 1e-6


@settings(max_examples=300, deadline=None)
@given(
    TYPES,
    SOURCES,
    st.sampled_from(["text_layer", "ocr", None]),
    st.booleans(),
    st.one_of(st.none(), st.floats(0, 1)),
    st.one_of(st.none(), st.floats(-1, 1)),
    st.one_of(st.none(), st.booleans()),
    st.integers(0, 5000),
    st.lists(st.sampled_from(["amount", "date", "party", "text"]), max_size=3),
    st.text(max_size=40),
)
def test_scores_are_bounded_capped_and_never_call_a_document_forged_or_authentic(
    kind: str,
    sources: list[str],
    method: str | None,
    digits_changed: bool,
    ocr_conf: float | None,
    page_ssim: float | None,
    vlm: bool | None,
    pixels: int,
    field_types: list[str],
    text: str,
) -> None:
    c = Candidate(
        kind,
        1,
        1,
        [1, 1, 9, 9],
        [1, 1, 9, 9],
        sources,
        original_text=text,
        test_text=text,
        method=method,
        digits_changed=digits_changed,
        metrics={"ocr_confidence": ocr_conf, "changed_pixels": pixels, "local_ssim": 0.2},
        fields=[{"name": f"f{i}", "value_type": t} for i, t in enumerate(field_types)],
        vlm=None if vlm is None else {"status": "assessed", "visible_difference": vlm},
    )
    score(c, page_ssim)
    assert 0.05 <= c.confidence <= 0.95
    assert c.severity in {"info", "low", "medium"}
    assert c.basis and c.explanation
    words = c.explanation.lower().replace(text.lower(), "")
    assert "forged" not in words and "authentic" not in words and "fraud" not in words


@settings(max_examples=60, deadline=None)
@given(st.lists(st.tuples(st.integers(1, 3), boxes), max_size=6))
def test_annotations_stay_inside_their_page(raw: list[tuple[int, list[float]]]) -> None:
    doc = pymupdf.open()
    doc.new_page(width=300, height=400)
    data = doc.tobytes()
    marks = [Mark(i + 1, page, box, "low", "m") for i, (page, box) in enumerate(raw)]
    out, stats = annotated_pdf(data, "application/pdf", marks, None, 72, 5)
    assert stats.drawn + stats.skipped == len(marks)
    with pymupdf.open(stream=out, filetype="pdf") as d:
        rects = [a.rect for a in d[0].annots() if a.type[1] == "Square"]
        assert len(rects) == stats.drawn
        assert all(d[0].rect.contains(r) for r in rects)


@settings(max_examples=200, deadline=None)
@given(boxes, st.integers(28, 2000), st.integers(28, 2000))
def test_in_image_accepts_only_ordered_boxes_within_the_image(
    b: list[float], w: int, h: int
) -> None:
    if in_image(b, w, h):
        assert b[0] < b[2] and b[1] < b[3]
        assert b[0] >= -2 and b[1] >= -2 and b[2] <= w + 2 and b[3] <= h + 2
