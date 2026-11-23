"""Risk Assessment: per finding, how strong the evidence is, how urgently a human should
review it, what is uncertain, and which innocent explanations remain possible (hypotheses).

The persisted anomaly score, evidence confidence and priority are attached unchanged: the
agent's judgement is kept next to them, never in place of them.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import Field

from app.agents.base import AgentOutput, AgentSpec, Facts, Gather, Strict
from app.agents.cross_reference import MAX_FINDINGS, evidence_facts
from app.agents.planner import EXAMPLE_ID


class Hypothesis(Strict):
    text: str = Field(min_length=1, max_length=600)


class RiskAssessment(Strict):
    finding_id: uuid.UUID
    evidence_strength: Literal["strong", "moderate", "weak"]
    review_urgency: Literal["high", "medium", "low"]
    uncertainty: str = Field(min_length=1, max_length=800)
    alternative_explanations: list[Hypothesis] = Field(default_factory=list, max_length=5)


class RiskOutput(AgentOutput):
    assessments: list[RiskAssessment] = Field(default_factory=list, max_length=12)


SCORE_KEYS = ("anomaly_score", "evidence_confidence", "priority", "severity", "status")


async def gather(g: Gather, prior: dict[str, Any]) -> Facts:
    findings = (await g.call("list_findings"))["findings"]
    evidence = []
    for f in findings[:MAX_FINDINGS]:
        res = await g.call("get_finding_evidence", finding_id=f["finding_id"])
        if "evidence" in res:
            evidence.append(
                {**evidence_facts(res), **{k: f[k] for k in (*SCORE_KEYS, "evidence_status")}}
            )
    cross = prior.get("cross_reference", {})
    forensics = prior.get("forensics", {})
    return Facts(
        {
            "findings": evidence,
            "missing_information": [m["text"] for m in cross.get("missing_information", [])],
            "forensic_summary": forensics.get("summary", ""),
        }
    )


async def finalize(
    out: dict[str, Any], facts: Facts, prior: dict[str, Any], g: Gather
) -> dict[str, Any]:
    by_id = {f["finding_id"]: f for f in facts.data["findings"]}
    assessments = []
    seen: set[str] = set()
    for a in out.get("assessments", []):
        if a["finding_id"] in seen or a["finding_id"] not in by_id:
            continue
        seen.add(a["finding_id"])
        assessments.append(
            {
                **a,
                "assessed": True,
                "alternative_explanations": [
                    {**h, "hypothesis": True} for h in a.get("alternative_explanations", [])
                ],
                "persisted_scores": {k: by_id[a["finding_id"]][k] for k in SCORE_KEYS},
            }
        )
    for finding_id, f in by_id.items():
        if finding_id not in seen:
            assessments.append(
                {
                    "finding_id": finding_id,
                    "assessed": False,
                    "uncertainty": "The model gave no assessment for this finding.",
                    "alternative_explanations": [],
                    "persisted_scores": {k: f[k] for k in SCORE_KEYS},
                }
            )
    return {**out, "assessments": assessments}


SPEC = AgentSpec(
    name="risk",
    title="Risk Assessment",
    role=(
        "For each finding, you judge how strong its evidence is and how urgently a human "
        "should review it, explain what remains uncertain, and list alternative innocent "
        "explanations (for example: the customs value may include freight and insurance "
        "(CIF) while the invoice is FOB). Alternative explanations are hypotheses to check, "
        "not conclusions. Never give a probability of fraud. Give exactly one assessment for "
        "every finding in the facts, using its finding_id."
    ),
    prompt_version="risk-v1",
    output_model=RiskOutput,
    example={
        "assessments": [
            {
                "finding_id": EXAMPLE_ID,
                "evidence_strength": "strong",
                "review_urgency": "high",
                "uncertainty": "The documents do not say whether freight is included.",
                "alternative_explanations": [{"text": "The higher value may include insurance."}],
            }
        ],
        "tool_requests": [],
    },
    gather=gather,
    finalize=finalize,
    summarize=lambda out: (
        f"{sum(1 for a in out.get('assessments', []) if a.get('assessed'))} "
        f"of {len(out.get('assessments', []))} finding(s) assessed"
    ),
)
