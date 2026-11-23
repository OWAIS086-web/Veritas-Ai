"""Evidence Graph: how documents, parties and findings connect, and which relationships the
findings contradict."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.agents.base import AgentOutput, AgentSpec, Facts, Gather, Statement
from app.agents.planner import EXAMPLE_ID

MAX_ENTITIES = 4


class GraphOutput(AgentOutput):
    observations: list[Statement] = Field(default_factory=list, max_length=8)


async def gather(g: Gather, prior: dict[str, Any]) -> Facts:
    graph = await g.call("get_case_graph")
    labels = {n["id"]: n["label"] for n in graph["nodes"]}
    edges = [
        {
            "relationship_id": e["relationship_id"],
            "type": e["type"],
            "from": labels.get(e["source"], e["source"]),
            "to": labels.get(e["target"], e["target"]),
            "finding_id": e["finding_id"],
            "evidence_count": e["evidence_count"],
        }
        for e in graph["edges"]
    ]
    parties = [n for n in graph["nodes"] if n["kind"] == "entity" and n["type"] == "organization"]
    relationships = []
    for n in parties[:MAX_ENTITIES]:
        res = await g.call("get_entity_relationships", entity_id=n["id"])
        relationships.append({"entity_id": n["id"], "name": n["label"], **res})
    return Facts(
        {
            "nodes": [{k: n[k] for k in ("id", "kind", "type", "label")} for n in graph["nodes"]],
            "edges": edges,
            "total_edges": graph["total_edges"],
            "party_relationships": relationships,
        }
    )


SPEC = AgentSpec(
    name="graph",
    title="Evidence Graph",
    role=(
        "You describe how the case's documents, parties and findings are connected: who "
        "issued or received each document, which documents contradict each other and which "
        "finding links them. Cite relationship_id, entity_id or finding_id."
    ),
    prompt_version="graph-v1",
    output_model=GraphOutput,
    example={
        "observations": [
            {
                "text": "The invoice and the customs declaration disagree on the total.",
                "refs": [{"relationship_id": EXAMPLE_ID, "finding_id": EXAMPLE_ID}],
            }
        ],
        "tool_requests": [],
    },
    gather=gather,
    summarize=lambda out: f"{len(out.get('observations', []))} graph observation(s)",
)
