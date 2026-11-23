"""Autonomous investigation API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ApiModel

InvestigationStatusValue = Literal[
    "queued", "running", "awaiting_review", "approved", "completed", "failed", "budget_exhausted"
]


class InvestigateRequest(BaseModel):
    objective: str = Field(min_length=3, max_length=1000)


class EvidenceRequestCreate(BaseModel):
    document_types: list[str] = Field(min_length=1, max_length=10)
    note: str = Field(min_length=3, max_length=2000)


class InvestigationOut(ApiModel):
    id: uuid.UUID
    case_id: uuid.UUID
    objective: str
    status: InvestigationStatusValue
    budget: dict[str, Any] = Field(description="Limits: iterations, tool calls, tokens, seconds")
    usage: dict[str, Any] = Field(
        description="Spent so far. `tokens` counts only provider-reported tokens; "
        "`unmetered_calls` counts model calls whose provider reported none."
    )
    error: str | None
    created_by: uuid.UUID | None
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class AgentRunOut(ApiModel):
    id: uuid.UUID
    agent: str
    status: str
    output_summary: str
    output: dict[str, Any]
    model: str | None
    provider: str | None
    prompt_version: str | None
    tool_calls: int
    tokens: int | None
    duration_ms: int | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class EvidenceRequestOut(ApiModel):
    id: uuid.UUID
    case_id: uuid.UUID
    investigation_id: uuid.UUID | None
    finding_id: uuid.UUID | None = None
    document_types: list[str]
    note: str
    status: str
    created_by: uuid.UUID | None
    created_at: datetime


class InvestigationDetail(InvestigationOut):
    result: dict[str, Any] = Field(
        description="Each agent's validated output (`agents`) and, after approval, the "
        "report draft (`report_draft`). Every citation in it resolved to a persisted row."
    )
    agent_runs: list[AgentRunOut] = Field(default_factory=list)
    evidence_requests: list[EvidenceRequestOut] = Field(default_factory=list)


class AgentEventOut(ApiModel):
    seq: int
    agent: str | None
    type: str
    data: dict[str, Any]
    created_at: datetime
