"""Cross-Reference: for each finding, the evidence that supports or conflicts with it, and
the information that is missing to explain it."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field

from app.agents.base import AgentOutput, AgentSpec, Facts, Gather, Statement, Strict
from app.agents.planner import EXAMPLE_ID

MAX_FINDINGS = 6


class Assessment(Strict):
    finding_id: uuid.UUID
    summary: str = Field(min_length=1, max_length=800)
    supporting: list[Statement] = Field(default_factory=list, max_length=6)
    conflicting: list[Statement] = Field(default_factory=list, max_length=6)


class Missing(Strict):
    text: str = Field(min_length=1, max_length=600)
    document_types: list[str] = Field(default_factory=list, max_length=6)


class CrossReferenceOutput(AgentOutput):
    assessments: list[Assessment] = Field(default_factory=list, max_length=12)
    missing_information: list[Missing] = Field(default_factory=list, max_length=8)


def evidence_facts(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "finding_id": evidence["finding_id"],
        "title": evidence["title"],
        "explanation": evidence["explanation"],
        "limitations": evidence["limitations"],
        "evidence": [
            {
                "document_id": e["document_id"],
                "filename": e["filename"],
                "field_id": e["field_id"],
                "field_name": e["field_name"],
                "page": e["page"],
                "value": e["value"],
                "role": e["role"],
            }
            for e in evidence["evidence"]
        ],
    }


async def gather(g: Gather, prior: dict[str, Any]) -> Facts:
    findings = (await g.call("list_findings"))["findings"]
    documents = (await g.call("list_case_documents"))["documents"]
    evidence = []
    for f in findings[:MAX_FINDINGS]:
        res = await g.call("get_finding_evidence", finding_id=f["finding_id"])
        if "evidence" in res:
            evidence.append(evidence_facts(res))
    return Facts(
        {
            "documents": [
                {
                    "document_id": d["document_id"],
                    "filename": d["filename"],
                    "doc_type": d["doc_type"],
                }
                for d in documents
            ],
            "findings": evidence,
            "missing_document_findings": [
                {"finding_id": f["finding_id"], "title": f["title"]}
                for f in findings
                if f["type"] == "missing_document"
            ],
        }
    )


async def finalize(
    out: dict[str, Any], facts: Facts, prior: dict[str, Any], g: Gather
) -> dict[str, Any]:
    missing = [{**m, "source": "model"} for m in out.get("missing_information", [])]
    # Absences the comparison rules already detected are listed as such, not re-derived.
    missing += [
        {"text": m["title"], "document_types": [], "source": "rule", "finding_id": m["finding_id"]}
        for m in facts.data["missing_document_findings"]
    ]
    return {**out, "missing_information": missing}


SPEC = AgentSpec(
    name="cross_reference",
    title="Cross-Reference",
    role=(
        "For each finding, you list the evidence that supports it and the evidence that "
        "conflicts with it, each citing field_id, document_id and page. Then you list the "
        "information that is missing to explain the finding (for example a freight invoice "
        "that would explain a value difference), with the document types that would supply it."
    ),
    prompt_version="cross-reference-v1",
    output_model=CrossReferenceOutput,
    example={
        "assessments": [
            {
                "finding_id": EXAMPLE_ID,
                "summary": "Two documents state one value and one states another.",
                "supporting": [
                    {
                        "text": "The invoice states USD 1,000.00.",
                        "refs": [{"document_id": EXAMPLE_ID, "page": 1, "field_id": EXAMPLE_ID}],
                    }
                ],
                "conflicting": [],
            }
        ],
        "missing_information": [
            {
                "text": "No freight invoice explains the difference.",
                "document_types": ["freight_invoice"],
            }
        ],
        "tool_requests": [],
    },
    gather=gather,
    finalize=finalize,
    summarize=lambda out: (
        f"{len(out.get('assessments', []))} finding(s) cross-referenced; "
        f"{len(out.get('missing_information', []))} missing item(s)"
    ),
)
