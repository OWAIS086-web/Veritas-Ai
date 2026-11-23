"""Generated reports. Every format renders from the same verified `model_json`, and the
stored file is kept with its SHA-256. A report whose citations don't resolve is `failed`
with the bad references and no file."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk

REPORT_FORMATS = ("pdf", "docx", "json", "xlsx")


class Report(UUIDPk, CreatedAt, Base):
    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint("format IN ('pdf', 'docx', 'json', 'xlsx')", name="format_known"),
        CheckConstraint(
            "status <> 'completed' OR (storage_key IS NOT NULL AND sha256 IS NOT NULL)",
            name="completed_has_file",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), index=True
    )
    investigation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("investigations.id", ondelete="SET NULL")
    )
    format: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(
        String(20), default="queued"
    )  # queued|running|completed|failed
    storage_key: Mapped[str | None] = mapped_column(String(200))
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    model_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    finished_at: Mapped[datetime | None]
