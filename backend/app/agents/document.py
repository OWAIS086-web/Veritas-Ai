"""Document Intelligence: what each document states, from its extracted fields and the text
of the pages that hold the values the findings are about."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field

from app.agents.base import AgentOutput, AgentSpec, Facts, Gather, Statement, Strict
from app.agents.planner import EXAMPLE_ID

MAX_DOCUMENTS = 10
MAX_PAGES = 4


class DocumentSummary(Strict):
    document_id: uuid.UUID
    summary: str = Field(min_length=1, max_length=800)
    facts: list[Statement] = Field(default_factory=list, max_length=6)


class DocumentOutput(AgentOutput):
    documents: list[DocumentSummary] = Field(default_factory=list, max_length=12)


async def gather(g: Gather, prior: dict[str, Any]) -> Facts:
    planner = prior.get("planner", {})
    docs = [d for d in planner.get("documents", []) if d.get("status") == "completed"]
    finding_fields = {f["field"] for f in planner.get("findings", []) if f.get("field")}
    documents: list[dict[str, Any]] = []
    wanted_pages: list[tuple[str, int]] = []
    for d in docs[:MAX_DOCUMENTS]:
        res = await g.call("get_document_fields", document_id=d["document_id"])
        fields = [
            {"field_id": f["field_id"], "name": f["name"], "value": f["value"], "page": f["page"]}
            for f in res.get("fields", [])
            if f.get("status") == "extracted"
        ]
        documents.append(
            {
                "document_id": d["document_id"],
                "filename": d["filename"],
                "doc_type": d["doc_type"],
                "fields": fields,
            }
        )
        for f in fields:
            key = (d["document_id"], f["page"])
            if f["name"] in finding_fields and f["page"] and key not in wanted_pages:
                wanted_pages.append(key)
    pages = []
    for document_id, page in wanted_pages[:MAX_PAGES]:
        text = await g.call("get_page_text", document_id=document_id, page=page)
        if "text" in text:
            pages.append({"document_id": document_id, "page": page, "text": text["text"]})
    return Facts({"documents": documents}, pages)


SPEC = AgentSpec(
    name="document",
    title="Document Intelligence",
    role=(
        "You summarize what each document states: its type, parties, references, dates and "
        "amounts. Every fact cites the field_id it comes from (with its document_id and "
        "page). Report values exactly as given."
    ),
    prompt_version="document-v1",
    output_model=DocumentOutput,
    example={
        "documents": [
            {
                "document_id": EXAMPLE_ID,
                "summary": "Commercial invoice from the supplier to the buyer.",
                "facts": [
                    {
                        "text": "The invoice total is USD 1,000.00.",
                        "refs": [{"document_id": EXAMPLE_ID, "page": 1, "field_id": EXAMPLE_ID}],
                    }
                ],
            }
        ],
        "tool_requests": [],
    },
    gather=gather,
    summarize=lambda out: f"{len(out.get('documents', []))} document(s) summarized",
)
