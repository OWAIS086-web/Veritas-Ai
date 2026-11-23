"""Findings API contracts. Decimals are serialized as strings."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ApiModel
from app.schemas.investigations import EvidenceRequestOut

FindingStatusValue = Literal[
    "new", "under_review", "confirmed_observation", "needs_more_evidence", "dismissed", "resolved"
]
Severity = Literal["info", "low", "medium", "high"]
PriorityLevel = Literal["low", "medium", "high"]


class FindingSummary(ApiModel):
    id: uuid.UUID
    case_id: uuid.UUID
    case_title: str = ""
    type: str
    title: str
    severity: Severity
    priority: PriorityLevel
    anomaly_score: Decimal | None = Field(
        description="Magnitude of the inconsistency (0..1). Not a likelihood of wrongdoing."
    )
    evidence_confidence: Decimal | None = Field(
        description="Lowest measured confidence of the cited fields; null if not measured."
    )
    field: str | None
    currency: str | None
    difference: Decimal | None
    status: FindingStatusValue
    evidence_status: Literal["supported", "absence"]
    evidence_count: int = 0
    assignee_user_id: uuid.UUID | None = None
    requires_human_review: bool
    active: bool = Field(description="False when the latest comparison no longer detects it.")
    detected_by: str
    last_detected_at: datetime
    created_at: datetime
    updated_at: datetime


class EvidenceOut(ApiModel):
    id: uuid.UUID
    document_id: uuid.UUID
    document_filename: str = ""
    doc_type: str | None = None
    extracted_field_id: uuid.UUID | None
    field_name: str
    page_number: int | None
    bbox: list[float] | None
    location: str | None
    value: str | None
    normalized_value: Any
    confidence: Decimal | None
    role: Literal["supporting", "conflicting", "context"]


class DecisionOut(ApiModel):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    actor_email: str | None = None
    from_status: str
    to_status: str
    note: str | None
    created_at: datetime


class CommentOut(ApiModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    user_email: str | None = None
    body: str
    created_at: datetime


class FindingDetail(FindingSummary):
    explanation: str
    severity_rationale: str
    limitations: list[str]
    recommended_action: str
    coverage: dict[str, Any]
    ai_output_json: dict[str, Any] = Field(
        description="The detector's original output, written once and never changed."
    )
    evidence: list[EvidenceOut] = Field(default_factory=list)
    decisions: list[DecisionOut] = Field(default_factory=list)
    comments: list[CommentOut] = Field(default_factory=list)
    assignee_email: str | None = None
    evidence_requests: list[EvidenceRequestOut] = Field(default_factory=list)


class AssigneeChange(BaseModel):
    user_id: uuid.UUID | None = Field(description="A member of the organization, or null to clear")


class StatusChange(BaseModel):
    status: FindingStatusValue
    note: str | None = Field(default=None, max_length=4000)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class CompareResponse(BaseModel):
    job_id: uuid.UUID
