"""Case, document, page and extraction API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import ApiModel

InvestigationType = Literal[
    "international_shipment", "trade_finance", "insurance_claim", "procurement", "other"
]
Priority = Literal["low", "medium", "high", "critical"]
CaseStatusLiteral = Literal["open", "closed"]


class CaseCreate(ApiModel):
    title: str = Field(min_length=3, max_length=200)
    objective: str = Field(default="", max_length=4000)
    investigation_type: InvestigationType = "international_shipment"
    priority: Priority = "medium"


class CaseUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    objective: str | None = Field(default=None, max_length=4000)
    priority: Priority | None = None
    status: CaseStatusLiteral | None = None


class CaseOut(ApiModel):
    id: uuid.UUID
    title: str
    objective: str
    investigation_type: str
    priority: str
    status: str
    created_by: uuid.UUID | None
    created_by_email: str | None = None
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    documents_completed: int = 0
    documents_failed: int = 0
    compared_at: datetime | None = Field(
        default=None, description="When the documents were last compared; null if never"
    )
    finding_count: int | None = Field(
        default=None,
        description="Active findings of the last comparison; null if the case was never compared",
    )


class StageOut(ApiModel):
    stage: str
    status: str
    attempts: int
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    metrics: dict[str, Any]


class DocumentOut(ApiModel):
    id: uuid.UUID
    case_id: uuid.UUID
    original_filename: str
    sha256: str
    mime_type: str
    detection_reason: str
    size_bytes: int
    page_count: int | None
    doc_type: str | None
    classification_confidence: Decimal | None = Field(
        description="Rule-match ratio of the classifier, not a probability"
    )
    language: str | None
    status: str
    current_stage: str | None
    error: str | None
    pipeline_version: str
    source_archive: str | None
    uploaded_at: datetime
    processed_at: datetime | None
    supersedes_id: uuid.UUID | None = None
    stages: list[StageOut] = Field(default_factory=list)


class UploadResult(ApiModel):
    filename: str
    status: Literal["accepted", "duplicate", "rejected"]
    document_id: uuid.UUID | None = None
    reason: str | None = None
    detected_type: str | None = None


class UploadResponse(ApiModel):
    results: list[UploadResult]
    job_id: uuid.UUID | None = Field(
        default=None, description="Processing job for the accepted files (stream its events)"
    )


class ProcessResponse(ApiModel):
    job_id: uuid.UUID | None
    document_ids: list[uuid.UUID]


class PageOut(ApiModel):
    page_number: int
    width: float | None
    height: float | None
    coord_unit: Literal["pt", "px"]
    method: str
    text: str
    lines: list[dict[str, Any]]
    tables: list[dict[str, Any]]
    ocr_mean_confidence: Decimal | None


class FieldOut(ApiModel):
    id: uuid.UUID
    name: str
    value: str | None
    normalized_value: Any
    value_type: str
    currency: str | None
    semantic_role: str | None
    confidence: Decimal | None = Field(
        description="From the text layer (1.0) or OCR; null when no measured confidence exists"
    )
    document_id: uuid.UUID
    page_number: int | None
    bbox: list[float] | None = Field(description="[x0, y0, x1, y1], top-left origin, page units")
    location: str | None
    method: str
    model_version: str
    status: Literal["extracted", "uncertain"]
    rejection_reason: str | None


class ExtractionOut(ApiModel):
    run_id: uuid.UUID
    document_id: uuid.UUID
    method: str
    provider: str | None
    model_version: str
    prompt_version: str | None
    pipeline_version: str
    notes: dict[str, Any]
    finished_at: datetime | None
    fields: list[FieldOut]


class PreviewOut(ApiModel):
    url: str
    expires_at: datetime
    mime_type: str
