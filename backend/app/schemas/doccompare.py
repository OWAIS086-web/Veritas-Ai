"""Original-versus-test document comparison API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ApiModel
from app.schemas.documents import UploadResult

ComparisonStatus = Literal["queued", "waiting_for_documents", "running", "completed", "failed"]
VlmStatus = Literal["used", "unavailable", "failed", "disabled", "not_run"]
ReviewStatus = Literal["unreviewed", "confirmed_difference", "needs_more_evidence", "dismissed"]
ExportKind = Literal["annotated_pdf", "annotated_images", "report_pdf", "findings_json"]
NOTE_REQUIRED = ("confirmed_difference", "dismissed")


class ComparisonCreate(BaseModel):
    original_document_id: uuid.UUID = Field(description="The reference document")
    test_document_id: uuid.UUID = Field(description="The document examined for differences")

    @model_validator(mode="after")
    def _distinct(self) -> ComparisonCreate:
        if self.original_document_id == self.test_document_id:
            raise ValueError("The original and the test document must be different documents.")
        return self


class ComparisonOut(ApiModel):
    id: uuid.UUID
    case_id: uuid.UUID
    original_document_id: uuid.UUID
    test_document_id: uuid.UUID
    original_filename: str | None = None
    test_filename: str | None = None
    status: ComparisonStatus
    stage: str | None
    progress: int = Field(description="0-100, persisted by the worker")
    vlm_status: VlmStatus
    vlm_model: str | None
    error: str | None
    created_by: uuid.UUID | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    findings_count: int = 0
    findings_unreviewed: int = 0


class ComparisonFindingOut(ApiModel):
    id: uuid.UUID
    number: int = Field(description="The number drawn on the annotated documents")
    type: str
    sources: list[str] = Field(description="ocr (text layer or OCR), cv (pixels), vlm")
    test_page: int | None
    original_page: int | None
    region: list[float] | None = Field(
        description="[x0, y0, x1, y1] on the test page, top-left origin, page units (validated)"
    )
    original_region: list[float] | None = Field(
        description="The same place on the original page (validated)"
    )
    original_text: str | None
    test_text: str | None
    severity: Literal["info", "low", "medium"]
    evidence_confidence: Decimal
    explanation: str
    metrics: dict[str, Any]
    vlm_assessment: dict[str, Any] | None
    review_status: ReviewStatus
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None


class ComparisonExportOut(ApiModel):
    id: uuid.UUID
    kind: ExportKind
    status: Literal["queued", "completed", "failed"]
    sha256: str | None
    size_bytes: int | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class ComparisonDetail(ComparisonOut):
    settings: dict[str, Any]
    summary: dict[str, Any] = Field(
        description="Documents and hashes, page alignment, counts, method and vision-model stats"
    )
    limitation: str
    findings: list[ComparisonFindingOut]
    exports: list[ComparisonExportOut]


class ComparisonUploadOut(ApiModel):
    comparison: ComparisonOut
    original: UploadResult
    test: UploadResult
    job_id: uuid.UUID | None = Field(
        default=None, description="Processing job for newly accepted files"
    )


class ReviewIn(BaseModel):
    status: ReviewStatus
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _note(self) -> ReviewIn:
        if self.status in NOTE_REQUIRED and not (self.note or "").strip():
            raise ValueError("A note is required to confirm or dismiss a difference.")
        return self


class ReviewEntryOut(ApiModel):
    id: uuid.UUID
    finding_id: uuid.UUID
    actor_user_id: uuid.UUID | None
    actor_email: str | None = None
    from_status: str
    to_status: str
    note: str | None
    created_at: datetime


class ExportCreate(BaseModel):
    kind: ExportKind


class VlmStatusOut(BaseModel):
    enabled: bool = Field(description="VERITAS_COMPARISON_VLM_ENABLED")
    configured: bool
    model: str | None
    endpoint_host: str | None
    reachable: bool
    model_available: bool
    error: str | None
