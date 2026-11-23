"""Regression: a PDF report whose table was wider than the page (unbroken SHA-256 values)
made PyMuPDF's Story repeat rows and then place nothing on every following page, forever. A
report on the stack held the only worker slot for 570 s until the time limit, and every queued
document waited behind it (found 2026-11-24 by the Playwright suite).

`tests/fixtures/report_story_loop.json` is that report's verified model (SYNTHETIC
DEMONSTRATION DATA from the end-to-end shipment case). Whether the loop happens depends on
where a page break falls, so the real content is the regression test."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pymupdf
import pytest

from app.integrations.pdf import story
from app.integrations.pdf.story import ZWSP, StoryLayoutError, render_story, soft_break
from app.services.reporting import render
from app.services.reporting.model import ReportModel

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "report_story_loop.json"


def _model() -> ReportModel:
    return ReportModel.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_the_report_that_looped_now_renders() -> None:
    started = time.monotonic()
    data = render.render(_model(), "pdf")
    assert time.monotonic() - started < 30
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        assert 3 <= len(doc) <= 10
        text = " ".join(p.get_text() for p in doc)
    assert "SYNTHETIC DEMONSTRATION DATA" in text and "Audit" in text  # the last section


def test_without_soft_breaks_the_guard_stops_it_instead_of_looping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(render, "soft_break", lambda text: text)
    started = time.monotonic()
    with pytest.raises(StoryLayoutError):
        render.render(_model(), "pdf")
    assert time.monotonic() - started < 60


def test_the_page_cap_applies_to_any_story(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(story, "MAX_PAGES", 2)
    rows = "".join(f"<tr><td>row {i}</td></tr>" for i in range(400))
    with pytest.raises(StoryLayoutError, match="2 pages"):
        render_story(f"<table>{rows}</table>", "td { font-size: 9pt; }")


def test_soft_break_only_touches_long_runs_of_letters_and_digits() -> None:
    h = "b9a348b7d64eff22eb7ddb76293f0411f737e2ac1e2e5a40295c5a94bca396c7"
    assert soft_break(h).replace(ZWSP, "") == h and ZWSP in soft_break(h)
    for unchanged in (
        "6f1c3a52-9d1e-4c84-bd2a-0c9f1f0b6f2e",
        "03_customs_declaration.pdf",
        "USD 68,000.00",
        "short words only",
    ):
        assert soft_break(unchanged) == unchanged
