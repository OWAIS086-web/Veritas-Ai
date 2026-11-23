"""Cases, documents, versions, processing stages, pages and extraction results."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk, utcnow


class CaseStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Case(UUIDPk, CreatedAt, Base):
    __tablename__ = "cases"
    __table_args__ = (Index("ix_cases_org_created", "organization_id", "created_at"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(200))
    objective: Mapped[str] = mapped_column(Text, default="")
    investigation_type: Mapped[str] = mapped_column(String(60))
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(20), default=CaseStatus.OPEN)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None]
    # Set by each completed cross-document comparison; null means "never compared".
    compared_at: Mapped[datetime | None]


class Document(UUIDPk, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "case_id", "sha256"),
        Index("ix_documents_case", "case_id"),
        Index("ix_documents_org_uploaded", "organization_id", "uploaded_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    original_filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(200))
    mime_type: Mapped[str] = mapped_column(String(120))
    detection_reason: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    page_count: Mapped[int | None] = mapped_column(Integer)
    doc_type: Mapped[str | None] = mapped_column(String(60))
    classification_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    language: Mapped[str | None] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(20), default=DocumentStatus.UPLOADED)
    current_stage: Mapped[str | None] = mapped_column(String(30))
    error: Mapped[str | None] = mapped_column(Text)
    pipeline_version: Mapped[str] = mapped_column(String(20))
    source_archive: Mapped[str | None] = mapped_column(String(255))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    uploaded_at: Mapped[datetime] = mapped_column(default=utcnow)
    processed_at: Mapped[datetime | None]


class DocumentVersion(UUIDPk, CreatedAt, Base):
    __tablename__ = "document_versions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    supersedes_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    sha256: Mapped[str] = mapped_column(String(64))


class DocumentStage(UUIDPk, Base):
    __tablename__ = "document_stages"
    __table_args__ = (UniqueConstraint("document_id", "stage", "pipeline_version"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(30))
    pipeline_version: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class DocumentPage(UUIDPk, Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    page_number: Mapped[int] = mapped_column(Integer)
    width: Mapped[float | None]
    height: Mapped[float | None]
    coord_unit: Mapped[str] = mapped_column(String(4))  # "pt" (PDF points) or "px" (images)
    method: Mapped[str] = mapped_column(String(20))  # text_layer | ocr | parser
    text: Mapped[str] = mapped_column(Text, default="")
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    tables: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    ocr_mean_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))


class ExtractionRun(UUIDPk, Base):
    __tablename__ = "extraction_runs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    pipeline_version: Mapped[str] = mapped_column(String(20))
    method: Mapped[str] = mapped_column(String(20))  # rules | llm
    provider: Mapped[str | None] = mapped_column(String(120))
    model_version: Mapped[str] = mapped_column(String(160))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    notes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None]


class ExtractedField(UUIDPk, Base):
    __tablename__ = "extracted_fields"
    __table_args__ = (Index("ix_extracted_fields_doc_name", "document_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(60))
    value: Mapped[str | None] = mapped_column(Text)
    normalized_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    value_type: Mapped[str] = mapped_column(String(20))
    currency: Mapped[str | None] = mapped_column(String(3))
    semantic_role: Mapped[str | None] = mapped_column(String(40))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    page_number: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)
    location: Mapped[str | None] = mapped_column(String(120))
    method: Mapped[str] = mapped_column(String(20))  # text_layer | ocr | parser | llm
    model_version: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20))  # extracted | uncertain
    rejection_reason: Mapped[str | None] = mapped_column(String(200))
