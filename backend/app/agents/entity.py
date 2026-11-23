"""Entity Resolution: the parties and things the case's documents mention, and where the
same name is written differently or may be a duplicate."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.agents.base import AgentOutput, AgentSpec, Facts, Gather, Statement
from app.agents.planner import EXAMPLE_ID

MAX_DETAILED = 6


class EntityOutput(AgentOutput):
    observations: list[Statement] = Field(default_factory=list, max_length=8)


async def gather(g: Gather, prior: dict[str, Any]) -> Facts:
    entities = (await g.call("list_entities"))["entities"]
    ranked = sorted(
        entities,
        key=lambda e: (e["status"] != "possible_duplicate", e["type"] != "organization"),
    )
    mentions = []
    for e in ranked[:MAX_DETAILED]:
        res = await g.call("get_entity_mentions", entity_id=e["entity_id"])
        if "mentions" in res:
            mentions.append(
                {
                    "entity_id": res["entity_id"],
                    "name": res["name"],
                    "status": res["status"],
                    "mentions": [
                        {k: m[k] for k in ("document_id", "filename", "field_id", "value", "page")}
                        for m in res["mentions"]
                    ],
                }
            )
    return Facts({"entities": entities, "mentions": mentions})


SPEC = AgentSpec(
    name="entity",
    title="Entity Resolution",
    role=(
        "You describe the organizations, shipments and other entities found in the case, "
        "how each is written across documents, and any name that may refer to the same "
        "entity. Cite entity_id, and field_id with document_id for each spelling."
    ),
    prompt_version="entity-v1",
    output_model=EntityOutput,
    example={
        "observations": [
            {
                "text": "The supplier is written in two ways that normalize to the same name.",
                "refs": [
                    {"entity_id": EXAMPLE_ID},
                    {"document_id": EXAMPLE_ID, "field_id": EXAMPLE_ID},
                ],
            }
        ],
        "tool_requests": [],
    },
    gather=gather,
    summarize=lambda out: f"{len(out.get('observations', []))} entity observation(s)",
)
