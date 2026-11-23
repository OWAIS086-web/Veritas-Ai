# Req: document-intelligence (provider extraction), ai-engineering steering (no fabrication)
"""Live run of the configured model provider on the synthetic shipment case.

Run explicitly: `pytest -m live`, with VERITAS_LIVE_LLM_BASE_URL (for example
http://127.0.0.1:11434/v1 for Ollama) and VERITAS_LIVE_LLM_MODEL set. Without them the test
fails instead of skipping, so a live run can't pass silently.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

from app.integrations.llm.openai_compat import OpenAICompatProvider
from app.services.extraction import llm
from app.services.parsing.dispatch import parse_document

pytestmark = pytest.mark.live
SAMPLES = Path(__file__).resolve().parents[3] / "sample-data"
MANIFEST = json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))["files"]


def _provider() -> OpenAICompatProvider:
    base = os.environ.get("VERITAS_LIVE_LLM_BASE_URL", "")
    model = os.environ.get("VERITAS_LIVE_LLM_MODEL", "")
    if not base or not model:
        pytest.fail("Set VERITAS_LIVE_LLM_BASE_URL and VERITAS_LIVE_LLM_MODEL for live tests")
    return OpenAICompatProvider(base, os.environ.get("VERITAS_LIVE_LLM_API_KEY", ""), [model], 180)


@pytest.mark.parametrize("name", sorted(p.name for p in (SAMPLES / "shipment-case").glob("*.pdf")))
async def test_model_values_that_pass_verification_match_the_ground_truth(name: str) -> None:
    truth = MANIFEST[f"shipment-case/{name}"]
    pages = parse_document((SAMPLES / "shipment-case" / name).read_bytes(), "application/pdf").pages
    values, notes = await llm.extract(_provider(), truth["doc_type"], pages)
    by_name = {v.name: v for v in values}
    assert notes["invalid_outputs"] <= llm.MAX_INVALID_RETRIES

    # A value is either verified on its page with its box, or uncertain with a reason.
    for v in values:
        if v.status == "extracted":
            assert v.page_number is not None and v.bbox is not None and v.normalized is not None
        else:
            assert v.rejection_reason, v

    number = by_name["document_number"]
    assert number.status == "extracted" and number.value == truth["document_number"]
    if "total_amount" in truth:
        total = by_name["total_amount"]
        if total.status == "extracted":
            assert Decimal(total.normalized["amount"]) == Decimal(truth["total_amount"])
            assert total.page_number == truth["total_page"]
        else:
            # A rejected claim must say why; the pipeline then uses the rules value.
            assert total.rejection_reason in {"value_not_on_cited_page", "model_returned_null"}
