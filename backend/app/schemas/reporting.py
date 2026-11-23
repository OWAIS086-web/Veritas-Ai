"""Report API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ApiModel

ReportFormat = Literal["pdf", "docx", "json", "xlsx"]


class ReportCreate(BaseModel):
    format: ReportFormat
    investigation_id: uuid.UUID | None = Field(
        default=None, description="An approved, completed investigation of the same case"
    )


class ReportOut(ApiModel):
    id: uuid.UUID
    case_id: uuid.UUID
    investigation_id: uuid.UUID | None
    format: ReportFormat
    status: Literal["queued", "running", "completed", "failed"]
    sha256: str | None
    size_bytes: int | None
    error: str | None = Field(description="For a failed report: the references that didn't resolve")
    created_by: uuid.UUID | None
    created_by_email: str | None = None
    created_at: datetime
    finished_at: datetime | None
    findings_total: int = 0
    findings_not_reviewed: int = Field(
        default=0, description="Findings labelled 'Not yet reviewed' when the report was generated"
    )


class ReportDetail(ReportOut):
    model: dict[str, Any] | None = Field(
        default=None, description="The verified report content every format was rendered from"
    )


class DownloadOut(BaseModel):
    url: str = Field(description="Signed link, valid for a short time")
    expires_at: datetime
