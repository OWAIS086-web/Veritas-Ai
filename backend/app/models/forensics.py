"""Forensic analysis runs and their anomalies, stored separately from extraction.

An anomaly is an observation for review, never a verdict. Its severity is capped at
`medium` in the database: a single forensic indicator never ranks above that.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk, utcnow

MANDATORY_LIMITATION = (
    "A visual or structural inconsistency alone does not establish document alteration or forgery."
)


class ForensicRun(UUIDPk, CreatedAt, Base):
    __tablename__ = "forensic_runs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    pipeline_version: Mapped[str] = mapped_column(String(20))
    analysis_types: Mapped[list[str]] = mapped_column(ARRAY(String(40)))
    pdf_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    structure: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    limitations: Mapped[list[str]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(20))  # succeeded | partial | not_applicable
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None]


class ForensicAnomaly(UUIDPk, CreatedAt, Base):
    __tablename__ = "forensic_anomalies"
    __table_args__ = (
        CheckConstraint("severity IN ('info', 'low', 'medium')", name="severity_capped"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    forensic_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forensic_runs.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(40))
    page_number: Mapped[int | None] = mapped_column(Integer)
    region: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)
    severity: Mapped[str] = mapped_column(String(10))
    explanation: Mapped[str] = mapped_column(Text)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=True)
