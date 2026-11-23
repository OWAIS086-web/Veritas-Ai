"""Permissioned tool layer. Agents reach data only through `ToolGateway.call`.

Each call is checked against the calling agent's allowlist, the arguments and the result are
validated with Pydantic, the permission is checked against the role that started the
investigation, the budget is charged, and an `agent_events` row is written. Every tool runs
in a tenant session and is scoped to the investigation's case: an id from another case or
organization is "not found". No tool can change a finding.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import results as r
from app.agents.events import InvestigationContext
from app.core.config import get_settings
from app.core.db import tenant_session
from app.core.errors import NotFoundError
from app.models import Investigation
from app.services.documents import service as documents
from app.services.findings import service as findings
from app.services.forensics import queries as forensics
from app.services.graph import queries as graph


class ToolRejected(Exception):
    """The call was refused before running (not allowed, unknown, bad arguments)."""

    def __init__(self, tool: str, reason: str) -> None:
        super().__init__(f"{tool}: {reason}")
        self.tool = tool
        self.reason = reason


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(_Args):
    pass


class DocumentArgs(_Args):
    document_id: uuid.UUID


class PageArgs(_Args):
    document_id: uuid.UUID
    page: int = Field(ge=1, le=10_000)


class FindingArgs(_Args):
    finding_id: uuid.UUID


class EntityArgs(_Args):
    entity_id: uuid.UUID


class ForensicArgs(_Args):
    document_id: uuid.UUID | None = None


class ReportDraftArgs(_Args):
    draft: dict[str, Any]


ToolFn = Callable[[AsyncSession, InvestigationContext, Any], Awaitable[BaseModel]]


@dataclass(frozen=True)
class Tool:
    name: str
    input_model: type[_Args]
    output_model: type[BaseModel]
    fn: ToolFn
    permission: str
    writes: bool = False


async def _case_document(s: AsyncSession, ctx: InvestigationContext, document_id: uuid.UUID) -> Any:
    doc = await documents.get_document(s, ctx.organization_id, document_id)
    if doc.case_id != ctx.case_id:
        raise NotFoundError("Document not found.")
    return doc


async def _list_case_documents(s: AsyncSession, ctx: InvestigationContext, _: NoArgs) -> BaseModel:
    docs = await documents.list_for_case(s, ctx.organization_id, ctx.case_id)
    return r.Documents(
        documents=[
            r.DocumentRow(
                document_id=d.id,
                filename=d.original_filename,
                doc_type=d.doc_type,
                status=d.status,
                page_count=d.page_count,
            )
            for d in docs
        ]
    )


async def _list_findings(s: AsyncSession, ctx: InvestigationContext, _: NoArgs) -> BaseModel:
    rows = await findings.list_for_case(s, ctx.organization_id, ctx.case_id, False)
    return r.Findings(findings=[r.FindingRow.from_summary(f) for f in rows])


async def _get_finding_evidence(
    s: AsyncSession, ctx: InvestigationContext, args: FindingArgs
) -> BaseModel:
    detail = await findings.get(s, ctx.organization_id, args.finding_id)
    if detail.case_id != ctx.case_id:
        raise NotFoundError("Finding not found.")
    return r.FindingEvidence.from_detail(detail)


async def _get_document_fields(
    s: AsyncSession, ctx: InvestigationContext, args: DocumentArgs
) -> BaseModel:
    doc = await _case_document(s, ctx, args.document_id)
    run = await documents.extractions(s, ctx.organization_id, args.document_id)
    fields = [r.FieldRow.from_field(f) for f in (run.fields if run else [])]
    return r.DocumentFields(
        document_id=doc.id, filename=doc.original_filename, doc_type=doc.doc_type, fields=fields
    )


async def _get_page_text(s: AsyncSession, ctx: InvestigationContext, args: PageArgs) -> BaseModel:
    await _case_document(s, ctx, args.document_id)
    pages = await documents.pages(s, ctx.organization_id, args.document_id)
    page = next((p for p in pages if p.page_number == args.page), None)
    if page is None:
        raise NotFoundError("Page not found.")
    limit = get_settings().investigation_max_page_chars
    return r.PageText(
        document_id=args.document_id,
        page=args.page,
        method=page.method,
        text=page.text[:limit],
        truncated=len(page.text) > limit,
    )


async def _get_forensic_results(
    s: AsyncSession, ctx: InvestigationContext, args: ForensicArgs
) -> BaseModel:
    if args.document_id is None:
        summary = await forensics.case_summary(s, ctx.organization_id, ctx.case_id)
        return r.ForensicSummary(documents=[r.ForensicDocRow.from_summary(x) for x in summary])
    await _case_document(s, ctx, args.document_id)
    run = await forensics.latest_run(s, ctx.organization_id, args.document_id)
    return r.ForensicDocument.from_run(args.document_id, run)


async def _list_entities(s: AsyncSession, ctx: InvestigationContext, _: NoArgs) -> BaseModel:
    out = await graph.case_graph(s, None, ctx.organization_id, ctx.case_id, None, None)
    return r.Entities(
        entities=[
            r.EntityRow(
                entity_id=n.id,
                type=n.type,
                name=n.label,
                status=str(n.properties.get("status", "")) or None,
                mention_count=int(n.properties.get("mention_count", 0) or 0),
            )
            for n in out.nodes
            if n.kind == "entity"
        ]
    )


async def _case_entity(s: AsyncSession, ctx: InvestigationContext, entity_id: uuid.UUID) -> Any:
    found = await graph.entity(s, ctx.organization_id, entity_id)
    if found.case_id != ctx.case_id:
        raise NotFoundError("Entity not found.")
    return found


async def _get_entity_mentions(
    s: AsyncSession, ctx: InvestigationContext, args: EntityArgs
) -> BaseModel:
    return r.EntityMentions.from_entity(await _case_entity(s, ctx, args.entity_id))


async def _get_case_graph(s: AsyncSession, ctx: InvestigationContext, _: NoArgs) -> BaseModel:
    out = await graph.case_graph(s, None, ctx.organization_id, ctx.case_id, None, None)
    return r.CaseGraph.from_graph(out)


async def _get_entity_relationships(
    s: AsyncSession, ctx: InvestigationContext, args: EntityArgs
) -> BaseModel:
    await _case_entity(s, ctx, args.entity_id)
    rels = await graph.entity_relationships(s, ctx.organization_id, args.entity_id)
    return r.Relationships(relationships=[r.RelationshipRow.from_out(x) for x in rels])


async def _create_report_draft(
    s: AsyncSession, ctx: InvestigationContext, args: ReportDraftArgs
) -> BaseModel:
    """The only writing tool: stores the draft on the investigation itself."""
    inv = await s.get(Investigation, ctx.investigation_id)
    if inv is None or inv.organization_id != ctx.organization_id:
        raise NotFoundError("Investigation not found.")
    await s.execute(
        update(Investigation)
        .where(
            Investigation.id == ctx.investigation_id,
            Investigation.organization_id == ctx.organization_id,
        )
        .values(result={**inv.result, "report_draft": args.draft})
    )
    return r.DraftSaved(saved=True, sections=len(args.draft.get("sections", [])))


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool("list_case_documents", NoArgs, r.Documents, _list_case_documents, "documents:read"),
        Tool("list_findings", NoArgs, r.Findings, _list_findings, "findings:read"),
        Tool(
            "get_finding_evidence",
            FindingArgs,
            r.FindingEvidence,
            _get_finding_evidence,
            "findings:read",
        ),
        Tool(
            "get_document_fields",
            DocumentArgs,
            r.DocumentFields,
            _get_document_fields,
            "documents:read",
        ),
        Tool("get_page_text", PageArgs, r.PageText, _get_page_text, "documents:read"),
        Tool(
            "get_forensic_results",
            ForensicArgs,
            r.ForensicResults,
            _get_forensic_results,
            "forensics:read",
        ),
        Tool("list_entities", NoArgs, r.Entities, _list_entities, "graph:read"),
        Tool(
            "get_entity_mentions",
            EntityArgs,
            r.EntityMentions,
            _get_entity_mentions,
            "graph:read",
        ),
        Tool("get_case_graph", NoArgs, r.CaseGraph, _get_case_graph, "graph:read"),
        Tool(
            "get_entity_relationships",
            EntityArgs,
            r.Relationships,
            _get_entity_relationships,
            "graph:read",
        ),
        Tool(
            "create_report_draft",
            ReportDraftArgs,
            r.DraftSaved,
            _create_report_draft,
            "investigations:run",
            writes=True,
        ),
    )
}

# The design's allowlists (.kiro/specs/autonomous-investigation/design.md).
ALLOWLISTS: dict[str, frozenset[str]] = {
    "planner": frozenset({"list_case_documents", "list_findings"}),
    "document": frozenset({"get_document_fields", "get_page_text"}),
    "forensics": frozenset({"get_forensic_results"}),
    "cross_reference": frozenset({"list_findings", "get_finding_evidence", "list_case_documents"}),
    "entity": frozenset({"list_entities", "get_entity_mentions"}),
    "graph": frozenset({"get_case_graph", "get_entity_relationships"}),
    "risk": frozenset({"list_findings", "get_finding_evidence"}),
    "report": frozenset({"create_report_draft"}),
}


class ToolGateway:
    def __init__(self, ctx: InvestigationContext, permissions: frozenset[str]) -> None:
        self.ctx = ctx
        self.permissions = permissions
        self.calls = 0

    async def _reject(
        self, agent: str, run_id: uuid.UUID | None, name: str, reason: str, detail: str = ""
    ) -> ToolRejected:
        await self.ctx.emit(
            "tool_rejected",
            {"tool": name[:80], "reason": reason, "detail": detail[:300]},
            agent=agent,
            run_id=run_id,
        )
        return ToolRejected(name, reason)

    async def call(
        self,
        agent: str,
        name: str,
        args: dict[str, Any],
        run_id: uuid.UUID | None = None,
        *,
        requested_by_model: bool = False,
    ) -> dict[str, Any]:
        tool = TOOLS.get(name)
        if tool is None:
            raise await self._reject(agent, run_id, name, "unknown_tool")
        if name not in ALLOWLISTS.get(agent, frozenset()):
            raise await self._reject(agent, run_id, name, "not_in_allowlist")
        if tool.writes and requested_by_model:
            # Writing tools run only from the agent's deterministic code, never on request.
            raise await self._reject(agent, run_id, name, "write_not_requestable")
        if tool.permission not in self.permissions:
            raise await self._reject(agent, run_id, name, "permission_denied", tool.permission)
        try:
            parsed = tool.input_model.model_validate(args)
        except ValidationError as exc:
            raise await self._reject(
                agent, run_id, name, "invalid_arguments", str(exc.errors()[:3])
            ) from exc
        self.ctx.budget.start_tool_call()
        self.calls += 1
        try:
            async with tenant_session(self.ctx.organization_id) as s:
                result = await tool.fn(s, self.ctx, parsed)
            payload = tool.output_model.model_validate(result.model_dump()).model_dump(mode="json")
        except NotFoundError as exc:
            await self.ctx.emit(
                "tool_failed",
                {"tool": name, "args": parsed.model_dump(mode="json"), "error": "not_found"},
                agent=agent,
                run_id=run_id,
            )
            return {"error": "not_found", "detail": str(exc)}
        await self.ctx.emit(
            "tool_called",
            {"tool": name, "args": parsed.model_dump(mode="json"), "result": r.brief(payload)},
            agent=agent,
            run_id=run_id,
        )
        return payload
