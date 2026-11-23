"""Original-versus-test document comparisons: the run, its findings (differences located on
the test document), the append-only review trail, and the generated exports.

A finding is an observed difference with its evidence and a measured evidence confidence. It
never states that a document is forged or authentic. Severity is capped at `medium` in the
database, as for forensic anomalies.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk

COMPARISON_LIMITATION = (
    "A difference between two files shows what changed, not who changed it or why; on its own "
    "it does not establish that either document is forged or authentic."
)
REVIEW_STATUSES = ("unreviewed", "confirmed_difference", "needs_more_evidence", "dismissed")
EXPORT_KINDS = ("annotated_pdf", "annotated_images", "report_pdf", "findings_json")


class DocumentComparison(UUIDPk, CreatedAt, Base):
    __tablename__ = "document_comparisons"
    __table_args__ = (
        CheckConstraint("original_document_id <> test_document_id", name="distinct_documents"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), index=True
    )
    original_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    test_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    # queued | waiting_for_documents | running | completed | failed
    status: Mapped[str] = mapped_column(String(30), default="queued")
    stage: Mapped[str | None] = mapped_column(String(40))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # used | unavailable | failed | disabled | not_run
    vlm_status: Mapped[str] = mapped_column(String(20), default="not_run")
    vlm_model: Mapped[str | None] = mapped_column(String(120))
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class ComparisonFinding(UUIDPk, CreatedAt, Base):
    __tablename__ = "comparison_findings"
    __table_args__ = (
        CheckConstraint("severity IN ('info', 'low', 'medium')", name="severity_capped"),
        CheckConstraint(
            "review_status IN ('unreviewed', 'confirmed_difference', 'needs_more_evidence', "
            "'dismissed')",
            name="review_status_known",
        ),
        CheckConstraint(
            "evidence_confidence >= 0 AND evidence_confidence <= 1", name="confidence_range"
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    comparison_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_comparisons.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)  # 1.. in reading order, shown on annotations
    type: Mapped[str] = mapped_column(String(40))
    sources: Mapped[list[str]] = mapped_column(ARRAY(String(20)))  # ocr | cv | vlm
    test_page: Mapped[int | None] = mapped_column(Integer)
    original_page: Mapped[int | None] = mapped_column(Integer)
    # [x0, y0, x1, y1], top-left origin, in each document's page units (validated in bounds).
    region: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)
    original_region: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)
    original_text: Mapped[str | None] = mapped_column(Text)
    test_text: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(10))
    evidence_confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    explanation: Mapped[str] = mapped_column(Text)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    vlm_assessment: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    review_status: Mapped[str] = mapped_column(String(30), default="unreviewed")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None]


class ComparisonReview(UUIDPk, CreatedAt, Base):
    """Append-only trail of review decisions on comparison findings."""

    __tablename__ = "comparison_reviews"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("comparison_findings.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    from_status: Mapped[str] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(Text)


class ComparisonExport(UUIDPk, CreatedAt, Base):
    __tablename__ = "comparison_exports"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('annotated_pdf', 'annotated_images', 'report_pdf', 'findings_json')",
            name="kind_known",
        ),
        CheckConstraint(
            "status <> 'completed' OR (storage_key IS NOT NULL AND sha256 IS NOT NULL)",
            name="completed_has_file",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    comparison_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_comparisons.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|completed|failed
    storage_key: Mapped[str | None] = mapped_column(String(200))
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    finished_at: Mapped[datetime | None] = mapped_column(default=None)


__all__ = [
    "COMPARISON_LIMITATION",
    "EXPORT_KINDS",
    "REVIEW_STATUSES",
    "ComparisonExport",
    "ComparisonFinding",
    "ComparisonReview",
    "DocumentComparison",
]
