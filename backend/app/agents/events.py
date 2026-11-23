"""The persisted record of an investigation: `agent_events` (append-only, ordered by `seq`)
and `agent_runs` (one row per agent step). The UI renders only these rows."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update

from app.agents.budget import Budget
from app.core.db import tenant_session
from app.models import AgentEvent, AgentRun, Investigation

MAX_EVENT_TEXT = 2000


def _clip(value: Any) -> Any:
    """Keep event payloads small: long strings are cut, nested values kept as they are."""
    if isinstance(value, str) and len(value) > MAX_EVENT_TEXT:
        return value[:MAX_EVENT_TEXT] + "…"
    if isinstance(value, dict):
        return {k: _clip(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clip(v) for v in value]
    return value


@dataclass
class InvestigationContext:
    """Everything a step needs: the tenant, the case, and the shared budget."""

    organization_id: uuid.UUID
    investigation_id: uuid.UUID
    case_id: uuid.UUID
    objective: str
    budget: Budget

    async def emit(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
        *,
        agent: str | None = None,
        run_id: uuid.UUID | None = None,
    ) -> int:
        """Append one event in its own transaction (so the SSE stream sees it at once)."""
        async with tenant_session(self.organization_id) as s:
            seq = await s.scalar(
                update(Investigation)
                .where(
                    Investigation.id == self.investigation_id,
                    Investigation.organization_id == self.organization_id,
                )
                .values(event_seq=Investigation.event_seq + 1, usage=self.budget.usage())
                .returning(Investigation.event_seq)
            )
            if seq is None:
                raise LookupError("investigation not found")
            s.add(
                AgentEvent(
                    organization_id=self.organization_id,
                    investigation_id=self.investigation_id,
                    agent_run_id=run_id,
                    seq=seq,
                    agent=agent,
                    type=event_type,
                    data=_clip(data or {}),
                )
            )
        return int(seq)

    async def start_run(self, agent: str, input_refs: dict[str, Any]) -> uuid.UUID:
        run_id = uuid.uuid4()
        async with tenant_session(self.organization_id) as s:
            s.add(
                AgentRun(
                    id=run_id,
                    organization_id=self.organization_id,
                    investigation_id=self.investigation_id,
                    agent=agent,
                    status="running",
                    input_refs=input_refs,
                )
            )
        await self.emit("agent_started", {"input_refs": input_refs}, agent=agent, run_id=run_id)
        return run_id

    async def finish_run(
        self,
        run_id: uuid.UUID,
        agent: str,
        *,
        status: str,
        output: dict[str, Any],
        summary: str,
        model: str | None,
        provider: str | None,
        prompt_version: str | None,
        tool_calls: int,
        tokens: int | None,
        started: datetime,
        error: str | None = None,
    ) -> None:
        finished = datetime.now(UTC)
        async with tenant_session(self.organization_id) as s:
            await s.execute(
                update(AgentRun)
                .where(AgentRun.id == run_id, AgentRun.organization_id == self.organization_id)
                .values(
                    status=status,
                    output=output,
                    output_summary=summary[:2000],
                    model=model,
                    provider=provider,
                    prompt_version=prompt_version,
                    tool_calls=tool_calls,
                    tokens=tokens,
                    duration_ms=int((finished - started).total_seconds() * 1000),
                    error=error,
                    finished_at=finished,
                )
            )
        await self.emit(
            "agent_completed" if status == "succeeded" else "agent_failed",
            {"summary": summary, "tool_calls": tool_calls, "tokens": tokens, "error": error},
            agent=agent,
            run_id=run_id,
        )
