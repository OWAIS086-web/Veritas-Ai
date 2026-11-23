"""Report Generation (after human approval): a structured report draft built from the
persisted outputs of the earlier agents. The model writes only the executive summary and
the review recommendations; a number or id in the summary that does not appear in the
structured content rejects the summary."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import Field

from app.agents.base import AgentOutput, AgentSpec, Facts, Gather, Statement
from app.agents.planner import EXAMPLE_ID

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class ReportOutput(AgentOutput):
    executive_summary: str = Field(min_length=1, max_length=2500)
    recommended_review: list[Statement] = Field(default_factory=list, max_length=8)


def _numbers(text: str) -> set[Decimal]:
    out: set[Decimal] = set()
    for raw in _NUMBER.findall(text):
        try:
            out.add(Decimal(raw.replace(",", "")).normalize())
        except InvalidOperation:
            continue
    return out


def unverified_tokens(summary: str, content: dict[str, Any]) -> list[str]:
    """Numbers and ids in the summary that the structured content doesn't contain."""
    source = json.dumps(content, default=str)
    known = _numbers(source)
    bad = [str(n) for n in _numbers(summary) if n not in known]
    bad += [i for i in _UUID.findall(summary.lower()) if i not in source]
    return bad


def content_from(prior: dict[str, Any]) -> dict[str, Any]:
    planner = prior.get("planner", {})
    return {
        "objective_focus": planner.get("focus"),
        "documents": [
            {k: d.get(k) for k in ("document_id", "filename", "doc_type")}
            for d in planner.get("documents", [])
        ],
        "findings": planner.get("findings", []),
        "document_summaries": prior.get("document", {}).get("documents", []),
        "forensics": {
            k: prior.get("forensics", {}).get(k)
            for k in ("summary", "observations", "limitations", "anomalies")
        },
        "cross_reference": prior.get("cross_reference", {}).get("assessments", []),
        "missing_information": prior.get("cross_reference", {}).get("missing_information", []),
        "entities": prior.get("entity", {}).get("observations", []),
        "relationships": prior.get("graph", {}).get("observations", []),
        "risk": prior.get("risk", {}).get("assessments", []),
    }


async def gather(g: Gather, prior: dict[str, Any]) -> Facts:
    return Facts(content_from(prior))


async def finalize(
    out: dict[str, Any], facts: Facts, prior: dict[str, Any], g: Gather
) -> dict[str, Any]:
    bad = unverified_tokens(out["executive_summary"], facts.data)
    findings = facts.data["findings"]
    summary = out["executive_summary"]
    if bad:
        summary = (
            f"The investigation reviewed {len(facts.data['documents'])} document(s) and "
            f"{len(findings)} finding(s). The model's summary was not used because it "
            "contained values that the structured content does not support."
        )
    draft = {
        "executive_summary": summary,
        "summary_status": "rejected" if bad else "verified",
        "unverified_tokens": bad,
        "sections": [
            {"key": "documents", "title": "Documents analyzed", "items": facts.data["documents"]},
            {"key": "discrepancies", "title": "Identified discrepancies", "items": findings},
            {"key": "cross_reference", "title": "Evidence", "items": facts.data["cross_reference"]},
            {
                "key": "forensics",
                "title": "Forensic observations",
                "items": [facts.data["forensics"]],
            },
            {"key": "entities", "title": "Entities identified", "items": facts.data["entities"]},
            {
                "key": "relationships",
                "title": "Relationship analysis",
                "items": facts.data["relationships"],
            },
            {
                "key": "missing_information",
                "title": "Missing supporting documents",
                "items": facts.data["missing_information"],
            },
            {
                "key": "alternative_explanations",
                "title": "Alternative explanations (hypotheses)",
                "items": [
                    {"finding_id": a["finding_id"], **h}
                    for a in facts.data["risk"]
                    for h in a.get("alternative_explanations", [])
                ],
            },
            {
                "key": "recommended_review",
                "title": "Recommended human review",
                "items": out.get("recommended_review", []),
            },
        ],
    }
    saved = await g.call("create_report_draft", draft=draft)
    return {
        **out,
        "executive_summary": summary,
        "summary_status": draft["summary_status"],
        "unverified_tokens": bad,
        "draft_saved": saved.get("saved", False),
    }


SPEC = AgentSpec(
    name="report",
    title="Report Generation",
    role=(
        "A human reviewer has approved the investigation. Write a short executive summary "
        "of the structured content and list what a human should review next. Use only "
        "numbers and ids that appear in the content."
    ),
    prompt_version="report-v1",
    output_model=ReportOutput,
    example={
        "executive_summary": "The documents disagree on the declared value of the shipment.",
        "recommended_review": [
            {"text": "Check the valuation basis.", "refs": [{"finding_id": EXAMPLE_ID}]}
        ],
        "tool_requests": [],
    },
    gather=gather,
    finalize=finalize,
    summarize=lambda out: f"Report draft saved ({out.get('summary_status')} summary)",
)
