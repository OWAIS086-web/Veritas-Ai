"""The investigation workflow: a LangGraph `StateGraph` of eight agents with a human-review
interrupt before the report, checkpointed in Postgres (`SqlCheckpointer`).

Planner → Document → Forensics → Cross-Reference → Entity → Graph → Risk → (human review)
→ Report. The graph is linear, so the only bound needed on cycles is the iteration budget,
which every agent step and every extra model round is charged against.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from itertools import pairwise
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select, update

from app.agents import cross_reference, document, entity, forensics, graph, planner, report, risk
from app.agents.base import AgentSpec
from app.agents.events import InvestigationContext
from app.agents.runner import AgentFailed, run_agent
from app.agents.tools import ToolGateway
from app.core.db import tenant_session
from app.integrations.llm.base import LLMProvider
from app.models import Investigation, InvestigationStatus
from app.workflows.checkpointer import SqlCheckpointer

AGENTS: list[AgentSpec] = [
    planner.SPEC,
    document.SPEC,
    forensics.SPEC,
    cross_reference.SPEC,
    entity.SPEC,
    graph.SPEC,
    risk.SPEC,
]
REVIEW_GATE = report.SPEC.name
RECURSION_LIMIT = 30


class InvestigationFailed(Exception):
    pass


def _merge(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    return {**(left or {}), **(right or {})}


class State(TypedDict, total=False):
    outputs: Annotated[dict[str, Any], _merge]


@dataclass
class Runtime:
    ctx: InvestigationContext
    gateway: ToolGateway
    provider: LLMProvider | None


async def _save_output(ctx: InvestigationContext, agent: str, output: dict[str, Any]) -> None:
    """Keep each agent's output on the investigation, so partial results survive a stop."""
    async with tenant_session(ctx.organization_id) as s:
        inv = await s.scalar(
            select(Investigation)
            .where(
                Investigation.id == ctx.investigation_id,
                Investigation.organization_id == ctx.organization_id,
            )
            .with_for_update()
        )
        if inv is None:
            raise InvestigationFailed("investigation not found")
        agents = {**inv.result.get("agents", {}), agent: output}
        await s.execute(
            update(Investigation)
            .where(Investigation.id == inv.id, Investigation.organization_id == inv.organization_id)
            .values(result={**inv.result, "agents": agents}, usage=ctx.budget.usage())
        )


def _node(spec: AgentSpec, rt: Runtime) -> Callable[[State], Awaitable[State]]:
    async def run(state: State) -> State:
        prior = dict(state.get("outputs") or {})
        if spec.name == REVIEW_GATE:
            async with tenant_session(rt.ctx.organization_id) as s:
                status = await s.scalar(
                    select(Investigation.status).where(
                        Investigation.id == rt.ctx.investigation_id,
                        Investigation.organization_id == rt.ctx.organization_id,
                    )
                )
            if status != InvestigationStatus.APPROVED:
                raise InvestigationFailed("the report step runs only after human approval")
        try:
            output = await run_agent(spec, rt.ctx, rt.gateway, rt.provider, prior)
        except AgentFailed as exc:
            if spec.name in (planner.SPEC.name, REVIEW_GATE):
                raise InvestigationFailed(f"{spec.name} failed: {exc.reason}") from exc
            # The other steps are independent views: a failed one is recorded and skipped.
            output = {"failed": True, "error": exc.reason}
        await _save_output(rt.ctx, spec.name, output)
        return {"outputs": {spec.name: output}}

    return run


def build_graph(rt: Runtime) -> Any:
    builder = StateGraph(State)
    names = [s.name for s in AGENTS] + [REVIEW_GATE]
    for spec in [*AGENTS, report.SPEC]:
        builder.add_node(spec.name, _node(spec, rt))  # type: ignore[call-overload]
    builder.add_edge(START, names[0])
    for a, b in pairwise(names):
        builder.add_edge(a, b)
    builder.add_edge(names[-1], END)
    return builder.compile(
        checkpointer=SqlCheckpointer(rt.ctx.organization_id), interrupt_before=[REVIEW_GATE]
    )


def thread_config(investigation_id: uuid.UUID) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": str(investigation_id)},
        "recursion_limit": RECURSION_LIMIT,
    }


async def advance(rt: Runtime) -> str:
    """Run (or resume) the workflow until it pauses for review or finishes. Returns
    `awaiting_review` or `completed`."""
    workflow = build_graph(rt)
    config = thread_config(rt.ctx.investigation_id)
    snapshot = await workflow.aget_state(config)
    first = not snapshot.values and not snapshot.next
    await workflow.ainvoke({"outputs": {}} if first else None, config)
    after = await workflow.aget_state(config)
    if REVIEW_GATE in (after.next or ()):
        return InvestigationStatus.AWAITING_REVIEW
    if after.next:
        raise InvestigationFailed(f"workflow stopped before {after.next}")
    return InvestigationStatus.COMPLETED
