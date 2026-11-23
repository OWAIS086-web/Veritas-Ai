"""Document forensics API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ApiModel


class ForensicAnomalyOut(ApiModel):
    id: uuid.UUID
    type: str
    page_number: int | None
    region: list[float] | None = Field(
        description="[x0, y0, x1, y1], top-left origin, in the document's page units"
    )
    severity: Literal["info", "low", "medium"]
    explanation: str
    metrics: dict[str, Any]
    requires_review: bool


class ForensicRunOut(ApiModel):
    id: uuid.UUID
    document_id: uuid.UUID
    pipeline_version: str
    analysis_types: list[str]
    pdf_metadata: dict[str, Any]
    structure: dict[str, Any]
    limitations: list[str]
    status: Literal["succeeded", "partial", "not_applicable"]
    started_at: datetime
    finished_at: datetime | None
    anomalies: list[ForensicAnomalyOut] = Field(default_factory=list)


class ForensicSummaryOut(BaseModel):
    document_id: uuid.UUID
    filename: str
    doc_type: str | None
    mime_type: str
    status: str | None = Field(description="Status of the latest forensic run; null if none")
    analysis_types: list[str] = Field(default_factory=list)
    anomalies: int = 0
    medium: int = 0
    low: int = 0
    types: list[str] = Field(default_factory=list)
