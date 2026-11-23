"""Live check of the comparison lab's vision step against a real Qwen2.5-VL server. Run
explicitly with `-m live` and VERITAS_LIVE_LLM_BASE_URL plus VERITAS_LIVE_VLM_MODEL (for example
qwen2.5vl:7b); without them the test fails instead of skipping.

The model's readings must agree with the text comparison, and nothing it returns may move a
region or create an unverified finding.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import pymupdf
import pytest

from app.integrations.llm.openai_compat import OpenAICompatProvider
from app.services.doccompare.engine import DocInput, EngineSettings, run
from app.services.doccompare.vision import Vision, VisionStats
from app.services.parsing.pdf import parse_text_page

pytestmark = pytest.mark.live
BASE = os.environ.get("VERITAS_LIVE_LLM_BASE_URL", "")
MODEL = os.environ.get("VERITAS_LIVE_VLM_MODEL", "")
ROOT = Path(__file__).resolve().parents[3] / "sample-data" / "comparison"
CFG = EngineSettings(144, 20, 1000, 0.6, 8, 1)


def _doc(name: str) -> DocInput:
    data = (ROOT / name).read_bytes()
    with pymupdf.open(stream=data, filetype="pdf") as d:
        pages = [
            {
                "page_number": i + 1,
                "method": "text_layer",
                "lines": [ln.to_json() for ln in parse_text_page(d[i], i + 1).lines],
            }
            for i in range(len(d))
        ]
    return DocInput(
        name, name, data, "application/pdf", hashlib.sha256(data).hexdigest(), pages, []
    )


async def _noop(stage: str, pct: int) -> None:
    return None


async def test_live_vision_model_agrees_and_never_moves_regions() -> None:
    if not (BASE and MODEL):
        pytest.fail("Set VERITAS_LIVE_LLM_BASE_URL and VERITAS_LIVE_VLM_MODEL for this live test")
    o, t = _doc("original_invoice.pdf"), _doc("test_altered.pdf")
    plain = await run(o, t, CFG, None, _noop)
    provider = OpenAICompatProvider(
        BASE, os.environ.get("VERITAS_LIVE_LLM_API_KEY", ""), [MODEL], 240
    )
    vision = Vision(provider, MODEL, VisionStats(model=MODEL))
    started = time.monotonic()
    seen = await run(o, t, CFG, vision, _noop)
    elapsed = time.monotonic() - started
    stats = seen.vlm or {}
    print(
        f"live {MODEL}: {stats.get('calls')} calls, {elapsed:.1f} s, {stats.get('tokens')} tokens"
    )
    assert stats["status"] == "used" and stats["errors"] == []
    # Every finding the model adds is pixel-verified; the deterministic ones keep their boxes.
    by_region = {tuple(f.region or []) for f in plain.findings}
    for f in seen.findings:
        if f.type == "vlm_observed_difference":
            assert "cv" in f.sources and f.metrics["changed_pixels"] >= 30
        else:
            assert tuple(f.region or []) in by_region
    assessed = [f for f in seen.findings if (f.vlm or {}).get("status") == "assessed"]
    assert assessed, "no region was assessed"
    agree = [f for f in assessed if f.vlm and f.vlm["visible_difference"] is True]
    assert len(agree) >= len(assessed) - 1, [f.vlm for f in assessed]
    consistent = [f for f in agree if (f.vlm or {})["text_check"]["test"] == "consistent"]
    print(f"{len(agree)}/{len(assessed)} regions confirmed, {len(consistent)} readings match OCR")
