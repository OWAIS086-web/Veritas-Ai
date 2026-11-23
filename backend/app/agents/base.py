"""Shared agent types: the output building blocks, the tool-request shape, and `AgentSpec`.

An agent gathers facts deterministically through its allowlisted tools, asks the model for a
structured answer (validated with Pydantic), may request more allowlisted data, and finishes
with deterministic post-processing. Its citations are validated before anything is stored.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agents.references import Ref
from app.agents.tools import ToolGateway, ToolRejected


class Strict(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Statement(Strict):
    text: str = Field(min_length=1, max_length=800)
    refs: list[Ref] = Field(default_factory=list, max_length=12)


class ToolRequest(Strict):
    tool: str = Field(max_length=80)
    args: dict[str, Any] = Field(default_factory=dict)


class AgentOutput(Strict):
    tool_requests: list[ToolRequest] = Field(default_factory=list, max_length=6)


@dataclass
class Gather:
    """Allowlisted tool access for one agent step, recording what was read."""

    gateway: ToolGateway
    agent: str
    run_id: uuid.UUID
    reads: list[dict[str, Any]] = field(default_factory=list)

    async def call(self, tool: str, **args: Any) -> dict[str, Any]:
        result = await self.gateway.call(self.agent, tool, args, self.run_id)
        self.reads.append({"tool": tool, "args": {k: str(v)[:80] for k, v in args.items()}})
        return result

    async def try_call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """A call the model asked for: a refusal is recorded and returned, not raised."""
        try:
            result = await self.gateway.call(
                self.agent, tool, args, self.run_id, requested_by_model=True
            )
        except ToolRejected as exc:
            return {"error": "rejected", "reason": exc.reason}
        self.reads.append({"tool": tool, "args": {k: str(v)[:80] for k, v in args.items()}})
        return result


@dataclass
class Facts:
    """What the model is shown: structured JSON facts and page text (as untrusted data)."""

    data: dict[str, Any]
    pages: list[dict[str, Any]] = field(default_factory=list)


GatherFn = Callable[[Gather, dict[str, Any]], Awaitable[Facts]]
FinalizeFn = Callable[[dict[str, Any], Facts, dict[str, Any], Gather], Awaitable[dict[str, Any]]]


async def keep(
    output: dict[str, Any], facts: Facts, prior: dict[str, Any], g: Gather
) -> dict[str, Any]:
    return output


@dataclass(frozen=True)
class AgentSpec:
    name: str
    title: str
    role: str
    prompt_version: str
    output_model: type[AgentOutput]
    example: dict[str, Any]
    gather: GatherFn
    finalize: FinalizeFn = keep
    # Short description of what the agent concluded, for the event log and the UI.
    summarize: Callable[[dict[str, Any]], str] = lambda out: ""
