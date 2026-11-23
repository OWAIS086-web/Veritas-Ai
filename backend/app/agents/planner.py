"""Planner: reads the case's documents and findings and states what to examine."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.agents.base import AgentOutput, AgentSpec, Facts, Gather, Statement

EXAMPLE_ID = "00000000-0000-0000-0000-000000000000"
PLAN = ["document", "forensics", "cross_reference", "entity", "graph", "risk"]


class PlannerOutput(AgentOutput):
    focus: str = Field(min_length=1, max_length=800)
    questions: list[Statement] = Field(default_factory=list, max_length=8)


async def gather(g: Gather, prior: dict[str, Any]) -> Facts:
    documents = (await g.call("list_case_documents"))["documents"]
    findings = (await g.call("list_findings"))["findings"]
    return Facts({"documents": documents, "findings": findings})


async def finalize(
    out: dict[str, Any], facts: Facts, prior: dict[str, Any], g: Gather
) -> dict[str, Any]:
    # The deterministic facts are kept for the next agents (their allowlists differ).
    return {**out, "plan": PLAN, **facts.data}


SPEC = AgentSpec(
    name="planner",
    title="Planner",
    role=(
        "You read the list of documents and the findings of a case and decide what the "
        "investigation must examine. State the focus in one paragraph and list the open "
        "questions, each citing the findings it is about."
    ),
    prompt_version="planner-v1",
    output_model=PlannerOutput,
    example={
        "focus": "<one paragraph, in your own words, about this case>",
        "questions": [
            {"text": "Which documents state each value?", "refs": [{"finding_id": EXAMPLE_ID}]}
        ],
        "tool_requests": [],
    },
    gather=gather,
    finalize=finalize,
    summarize=lambda out: f"{len(out.get('questions', []))} question(s); {out.get('focus', '')}",
)
