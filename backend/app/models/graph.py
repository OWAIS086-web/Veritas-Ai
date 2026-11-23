"""Entities, their mentions, evidence-backed relationships, and the graph outbox.

Postgres is the source of truth. These rows are derived from extracted fields and findings,
rebuilt per case with deterministic ids, and projected into Neo4j through the outbox.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, utcnow


class Entity(CreatedAt, Base):
    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("case_id", "type", "normalized_name"),
        Index("ix_entities_org_case", "organization_id", "case_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(30))  # organization | shipment | transaction | ...
    canonical_name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    status: Mapped[str] = mapped_column(String(30))  # resolved | possible_duplicate
    mention_count: Mapped[int] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class EntityMention(CreatedAt, Base):
    __tablename__ = "entity_mentions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    extracted_field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extracted_fields.id", ondelete="CASCADE")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    field_name: Mapped[str] = mapped_column(String(60))
    value: Mapped[str | None] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)
    location: Mapped[str | None] = mapped_column(String(120))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))


class Relationship(CreatedAt, Base):
    __tablename__ = "relationships"
    __table_args__ = (
        CheckConstraint("cardinality(evidence_ids) > 0", name="evidence_required"),
        CheckConstraint(
            "type <> 'CONTRADICTS' OR finding_id IS NOT NULL", name="contradicts_has_finding"
        ),
        Index("ix_relationships_org_case", "organization_id", "case_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(30))
    source_kind: Mapped[str] = mapped_column(String(20))  # document | entity | finding
    source_id: Mapped[uuid.UUID]
    target_kind: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[uuid.UUID]
    # extracted_fields or evidence_items ids; a trigger checks that each one exists.
    evidence_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid()))
    finding_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE")
    )
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class OutboxEvent(CreatedAt, Base):
    __tablename__ = "outbox"
    __table_args__ = (Index("ix_outbox_status_available", "status", "available_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    target: Mapped[str] = mapped_column(String(20))  # neo4j
    op: Mapped[str] = mapped_column(String(40))  # case.replace
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending|processing|done|dead
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    available_at: Mapped[datetime] = mapped_column(default=utcnow)
    claimed_at: Mapped[datetime | None]
    processed_at: Mapped[datetime | None]
