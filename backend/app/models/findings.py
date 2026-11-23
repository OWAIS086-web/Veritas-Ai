"""Findings, their evidence, human decisions and comments.

A finding is an observation for human review, never a verdict. Its three scores are kept
separate: anomaly_score (magnitude), evidence_confidence (from the cited fields) and
priority (what to look at first).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk, utcnow


class FindingStatus(StrEnum):
    NEW = "new"
    UNDER_REVIEW = "under_review"
    CONFIRMED_OBSERVATION = "confirmed_observation"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    DISMISSED = "dismissed"
    RESOLVED = "resolved"


class Finding(UUIDPk, CreatedAt, Base):
    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("case_id", "finding_key"),
        Index("ix_findings_org_case", "organization_id", "case_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    finding_key: Mapped[str] = mapped_column(String(200))  # rule_id:field_signature
    rule_id: Mapped[str] = mapped_column(String(60))
    detected_by: Mapped[str] = mapped_column(String(80))  # rule_id@version
    type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    severity: Mapped[str] = mapped_column(String(20))  # info | low | medium | high
    field: Mapped[str | None] = mapped_column(String(60))
    currency: Mapped[str | None] = mapped_column(String(3))
    difference: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    explanation: Mapped[str] = mapped_column(Text)
    severity_rationale: Mapped[str] = mapped_column(Text)
    limitations: Mapped[list[str]] = mapped_column(JSONB, default=list)
    anomaly_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    evidence_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    priority: Mapped[str] = mapped_column(String(20))  # low | medium | high
    evidence_status: Mapped[str] = mapped_column(String(20))  # supported | absence
    status: Mapped[str] = mapped_column(String(30), default=FindingStatus.NEW)
    # The investigator responsible for reviewing it (a member of the organization).
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=True)
    recommended_action: Mapped[str] = mapped_column(Text)
    coverage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # The detector's original output. Written once; a trigger rejects any change.
    ai_output_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # False when the latest comparison no longer detects it (the row and decisions stay).
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_detected_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class EvidenceItem(UUIDPk, CreatedAt, Base):
    __tablename__ = "evidence_items"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    # Null only after the field's extraction run was replaced; the next comparison
    # re-links the evidence to the new field row.
    extracted_field_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extracted_fields.id", ondelete="SET NULL")
    )
    field_name: Mapped[str] = mapped_column(String(60))
    page_number: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)
    location: Mapped[str | None] = mapped_column(String(120))
    value: Mapped[str | None] = mapped_column(Text)
    normalized_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    role: Mapped[str] = mapped_column(String(20))  # supporting | conflicting | context


class FindingDecision(UUIDPk, CreatedAt, Base):
    __tablename__ = "finding_decisions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    from_status: Mapped[str] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(Text)


class InvestigatorComment(UUIDPk, CreatedAt, Base):
    __tablename__ = "investigator_comments"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
