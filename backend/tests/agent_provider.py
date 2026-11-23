"""A scripted model for investigation tests (a test double; never used by the app).

It answers each agent from the facts in its prompt, citing only ids found there, the way a
well-behaved model should. Options inject the failures the safety layer must catch.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.integrations.llm.base import Completion, ProviderError

INVENTED = "11111111-2222-3333-4444-555555555555"
_AGENT = re.compile(r"You are the (.+?) agent of VERITAS")


def facts_of(user: str) -> dict[str, Any]:
    start = user.index("Facts (JSON):\n") + len("Facts (JSON):\n")
    value, _ = json.JSONDecoder().raw_decode(user[start:])
    return dict(value)


@dataclass
class ScriptedProvider:
    name: str = "scripted"
    invent_reference: bool = False  # cite a finding that doesn't exist
    request_forbidden_tool: bool = False  # ask for a tool outside the allowlist
    invalid_first: bool = False  # first answer of each agent fails validation
    never_finish: str | None = None  # this agent keeps requesting tools forever
    fail_agents: set[str] = field(default_factory=set)  # provider error for these agents
    usage: bool = True
    calls: list[tuple[str, list[dict[str, str]]]] = field(default_factory=list)
    _invalid_sent: set[str] = field(default_factory=set)

    async def complete_json(self, messages: list[dict[str, str]]) -> Completion:
        system, user = messages[0]["content"], messages[1]["content"]
        match = _AGENT.search(system)
        agent = match.group(1) if match else "?"
        self.calls.append((agent, messages))
        if agent in self.fail_agents:
            raise ProviderError("all models failed: scripted outage")
        if self.invalid_first and agent not in self._invalid_sent:
            self._invalid_sent.add(agent)
            # `tool_requests` must be a list in every agent's output model.
            return self._done({"tool_requests": "not a list"}, user)
        facts = facts_of(user)
        content = ANSWERS[agent](facts, self)
        if self.never_finish == agent:
            content["tool_requests"] = [{"tool": "list_findings", "args": {}}]
        elif self.request_forbidden_tool and agent == "Risk Assessment":
            content["tool_requests"] = [
                {"tool": "change_finding_status", "args": {"status": "dismissed"}},
                {"tool": "get_page_text", "args": {"document_id": INVENTED, "page": 1}},
            ]
            self.request_forbidden_tool = False
        return self._done(content, user)

    def _done(self, content: dict[str, Any], user: str) -> Completion:
        usage = {"prompt_tokens": len(user) // 4, "completion_tokens": 50} if self.usage else None
        return Completion(content, "scripted-model", self.name, 1, usage)


def _ref(**kw: Any) -> dict[str, Any]:
    return {k: v for k, v in kw.items() if v is not None}


def planner(f: dict[str, Any], p: ScriptedProvider) -> dict[str, Any]:
    return {
        "focus": "Explain the differences between the declared values.",
        "questions": [
            {"text": f"What explains: {x['title']}?", "refs": [_ref(finding_id=x["finding_id"])]}
            for x in f["findings"][:3]
        ],
    }


def document(f: dict[str, Any], p: ScriptedProvider) -> dict[str, Any]:
    out = []
    for d in f["documents"]:
        facts = [
            {
                "text": f"{x['name']} is {x['value']}.",
                "refs": [
                    _ref(document_id=d["document_id"], page=x["page"], field_id=x["field_id"])
                ],
            }
            for x in d["fields"]
            if x["name"] == "total_amount"
        ]
        out.append(
            {"document_id": d["document_id"], "summary": f"{d['filename']}.", "facts": facts}
        )
    return {"documents": out}


def forensics(f: dict[str, Any], p: ScriptedProvider) -> dict[str, Any]:
    total = sum(int(d.get("anomalies") or 0) for d in f["documents"])
    return {"summary": f"{total} forensic anomaly(ies) in the case.", "observations": []}


def cross_reference(f: dict[str, Any], p: ScriptedProvider) -> dict[str, Any]:
    assessments = [
        {
            "finding_id": x["finding_id"],
            "summary": x["title"],
            "supporting": [
                {
                    "text": f"{e['filename']} states {e['value']}.",
                    "refs": [
                        _ref(document_id=e["document_id"], page=e["page"], field_id=e["field_id"])
                    ],
                }
                for e in x["evidence"][:3]
            ],
            "conflicting": [],
        }
        for x in f["findings"]
    ]
    if p.invent_reference:
        assessments.append(
            {"finding_id": INVENTED, "summary": "A finding the model made up.", "supporting": []}
        )
        if assessments and assessments[0]["supporting"]:
            assessments[0]["supporting"].append(
                {"text": "An invented citation.", "refs": [{"field_id": INVENTED}]}
            )
    return {
        "assessments": assessments,
        "missing_information": [
            {
                "text": "No freight invoice explains the difference.",
                "document_types": ["freight_invoice"],
            }
        ],
    }


def entity(f: dict[str, Any], p: ScriptedProvider) -> dict[str, Any]:
    return {
        "observations": [
            {
                "text": f"{e['name']} appears in {len(e['mentions'])} field(s).",
                "refs": [_ref(entity_id=e["entity_id"])],
            }
            for e in f["mentions"][:3]
        ]
    }


def graph(f: dict[str, Any], p: ScriptedProvider) -> dict[str, Any]:
    return {
        "observations": [
            {
                "text": f"{e['from']} {e['type']} {e['to']}.",
                "refs": [_ref(relationship_id=e["relationship_id"], finding_id=e["finding_id"])],
            }
            for e in f["edges"]
            if e["type"] == "CONTRADICTS"
        ][:3]
    }


def risk(f: dict[str, Any], p: ScriptedProvider) -> dict[str, Any]:
    return {
        "assessments": [
            {
                "finding_id": x["finding_id"],
                "evidence_strength": "strong" if x["evidence"] else "weak",
                "review_urgency": "high" if x["severity"] == "high" else "low",
                "uncertainty": "The documents do not state whether freight is included.",
                "alternative_explanations": [
                    {
                        "text": "The customs value may include freight and insurance (CIF) "
                        "while the invoice is FOB."
                    }
                ],
            }
            for x in f["findings"]
        ]
    }


def report(f: dict[str, Any], p: ScriptedProvider) -> dict[str, Any]:
    differences = [x["difference"] for x in f["findings"] if x.get("difference")]
    summary = f"The documents of the case show {len(f['findings'])} finding(s)."
    if differences:
        summary += f" The declared totals differ by {differences[0]}."
    if p.invent_reference:
        summary += " A further 999,999.00 is unaccounted for."
    return {
        "executive_summary": summary,
        "recommended_review": [
            {"text": "Check the valuation basis.", "refs": [_ref(finding_id=x["finding_id"])]}
            for x in f["findings"][:2]
        ],
    }


ANSWERS = {
    "Planner": planner,
    "Document Intelligence": document,
    "Forensics": forensics,
    "Cross-Reference": cross_reference,
    "Entity Resolution": entity,
    "Evidence Graph": graph,
    "Risk Assessment": risk,
    "Report Generation": report,
}

__all__ = ["INVENTED", "ScriptedProvider", "facts_of", "uuid"]
