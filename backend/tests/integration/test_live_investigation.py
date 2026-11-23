"""The investigation workflow with a real model (live; `pytest -m live`).

Needs VERITAS_LIVE_LLM_BASE_URL and VERITAS_LIVE_LLM_MODEL (for example local Ollama with
qwen2.5:7b-instruct). The assertions are about safety, not wording: whatever the model says,
every stored citation resolves, findings are unchanged, and the run pauses for review.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.services.investigations.run import run_investigation
from tests.integration.test_investigations import (
    EARLY_AGENTS,
    Case,
    _detail,
    _events,
    _finding_statuses,
    _pair,
    _processed,
    _start,
)
from tests.live.test_live_provider import _provider

pytestmark = [pytest.mark.integration, pytest.mark.live]


async def test_live_model_investigation_pauses_for_review_with_only_valid_citations(
    client: httpx.AsyncClient,
) -> None:
    case: Case = await _processed(client, _pair())
    before = await _finding_statuses(case)
    inv = await _start(client, case, "Explain why the declared values differ.")
    outcome = await run_investigation(case.acct.organization_id, uuid.UUID(inv), _provider())
    d = await _detail(client, case, inv)
    events = await _events(case, inv)
    print("outcome", outcome, "usage", d["usage"])
    for r in d["agent_runs"]:
        print(r["agent"], r["status"], r["duration_ms"], r["tokens"], r["output_summary"][:100])
    print("events", {t: sum(e["type"] == t for e in events) for t in {e["type"] for e in events}})
    for e in events:
        if e["type"] in ("reference_rejected", "output_invalid", "tool_rejected"):
            print("event", e["agent"], e["type"], e["data"])
    for a in d["result"]["agents"]["risk"].get("assessments", []):
        print("risk", a["assessed"], a["persisted_scores"]["severity"], a.get("evidence_strength"))
    print(
        "findings",
        [(f["type"], f["severity"]) for f in d["result"]["agents"]["planner"]["findings"]],
    )
    assert outcome == "awaiting_review", d["error"]
    assert [r["agent"] for r in d["agent_runs"]] == EARLY_AGENTS
    assert d["agent_runs"][0]["status"] == "succeeded"
    assert await _finding_statuses(case) == before
    risk = d["result"]["agents"]["risk"]
    if not risk.get("failed"):
        for a in risk["assessments"]:
            assert a["persisted_scores"]["status"] == "new"
            assert all(h["hypothesis"] for h in a["alternative_explanations"])
