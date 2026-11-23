"""Forensics: what the persisted forensic runs observed, with their limitations."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.agents.base import AgentOutput, AgentSpec, Facts, Gather, Statement
from app.agents.planner import EXAMPLE_ID
from app.models.forensics import MANDATORY_LIMITATION

MAX_DETAILED = 5


class ForensicsOutput(AgentOutput):
    summary: str = Field(min_length=1, max_length=1200)
    observations: list[Statement] = Field(default_factory=list, max_length=10)


async def gather(g: Gather, prior: dict[str, Any]) -> Facts:
    summary = (await g.call("get_forensic_results")).get("documents") or []
    details = []
    for row in [x for x in summary if x.get("anomalies")][:MAX_DETAILED]:
        res = await g.call("get_forensic_results", document_id=row["document_id"])
        details.append(
            {
                "document_id": row["document_id"],
                "filename": row["filename"],
                "anomalies": res.get("anomalies") or [],
                "limitations": res.get("limitations") or [],
            }
        )
    return Facts({"documents": summary, "anomalies_by_document": details})


async def finalize(
    out: dict[str, Any], facts: Facts, prior: dict[str, Any], g: Gather
) -> dict[str, Any]:
    limitations = [MANDATORY_LIMITATION]
    for d in facts.data["anomalies_by_document"]:
        limitations += [x for x in d["limitations"] if x not in limitations]
    analysed = [d for d in facts.data["documents"] if d.get("status")]
    return {
        **out,
        "limitations": limitations,
        "documents_analysed": len(analysed),
        "anomalies": sum(int(d.get("anomalies") or 0) for d in facts.data["documents"]),
    }


SPEC = AgentSpec(
    name="forensics",
    title="Forensics",
    role=(
        "You explain what the forensic analyses observed for each document (PDF structure, "
        "compression, version differences, stamps). An anomaly is an observation for human "
        "review, never proof of alteration. If no anomaly was found, say so. Cite "
        "anomaly_id and document_id."
    ),
    prompt_version="forensics-v1",
    output_model=ForensicsOutput,
    example={
        "summary": "No forensic anomaly was found in the analysed documents.",
        "observations": [
            {
                "text": "The invoice was saved twice (an incremental update).",
                "refs": [{"document_id": EXAMPLE_ID, "anomaly_id": EXAMPLE_ID}],
            }
        ],
        "tool_requests": [],
    },
    gather=gather,
    finalize=finalize,
    summarize=lambda out: out.get("summary", ""),
)
