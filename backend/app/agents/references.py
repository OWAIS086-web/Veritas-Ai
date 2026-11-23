"""Reference validation. A model's citation is a claim until it resolves to a real row of the
same organization and case; anything else is removed and recorded as `reference_rejected`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Document,
    DocumentPage,
    Entity,
    ExtractedField,
    Finding,
    ForensicAnomaly,
    Relationship,
)


class Ref(BaseModel):
    """A citation. At least one id must be given; a page needs its document."""

    model_config = ConfigDict(extra="ignore")

    document_id: uuid.UUID | None = None
    page: int | None = None
    field_id: uuid.UUID | None = None
    finding_id: uuid.UUID | None = None
    entity_id: uuid.UUID | None = None
    relationship_id: uuid.UUID | None = None
    anomaly_id: uuid.UUID | None = None

    def is_empty(self) -> bool:
        return not any(
            (
                self.document_id,
                self.field_id,
                self.finding_id,
                self.entity_id,
                self.relationship_id,
                self.anomaly_id,
            )
        )


@dataclass(frozen=True)
class Rejected:
    ref: Ref
    reason: str


async def _one(s: AsyncSession, org: uuid.UUID, case: uuid.UUID, ref: Ref) -> str | None:
    """None when the reference is valid, else the reason it isn't."""
    if ref.is_empty():
        return "empty_reference"
    if ref.page is not None and ref.document_id is None:
        return "page_without_document"
    if ref.document_id is not None:
        doc_case = await s.scalar(
            select(Document.case_id).where(
                Document.id == ref.document_id, Document.organization_id == org
            )
        )
        if doc_case != case:
            return "document_not_in_case"
        if ref.page is not None:
            page = await s.scalar(
                select(DocumentPage.id).where(
                    DocumentPage.document_id == ref.document_id,
                    DocumentPage.organization_id == org,
                    DocumentPage.page_number == ref.page,
                )
            )
            if page is None:
                return "page_not_in_document"
    if ref.field_id is not None:
        row = (
            await s.execute(
                select(ExtractedField.document_id, ExtractedField.page_number, Document.case_id)
                .join(Document, Document.id == ExtractedField.document_id)
                .where(ExtractedField.id == ref.field_id, ExtractedField.organization_id == org)
            )
        ).first()
        if row is None or row.case_id != case:
            return "field_not_in_case"
        if ref.document_id is not None and row.document_id != ref.document_id:
            return "field_not_in_document"
        if ref.page is not None and row.page_number is not None and row.page_number != ref.page:
            return "field_not_on_page"
    checks: list[tuple[uuid.UUID | None, Any, str]] = [
        (ref.finding_id, Finding, "finding_not_in_case"),
        (ref.entity_id, Entity, "entity_not_in_case"),
        (ref.relationship_id, Relationship, "relationship_not_in_case"),
    ]
    for value, model, reason in checks:
        if value is None:
            continue
        found = await s.scalar(
            select(model.case_id).where(model.id == value, model.organization_id == org)
        )
        if found != case:
            return reason
    if ref.anomaly_id is not None:
        anomaly_case = await s.scalar(
            select(Document.case_id)
            .join(ForensicAnomaly, ForensicAnomaly.document_id == Document.id)
            .where(ForensicAnomaly.id == ref.anomaly_id, ForensicAnomaly.organization_id == org)
        )
        if anomaly_case != case:
            return "anomaly_not_in_case"
    return None


async def validate_refs(
    s: AsyncSession, org: uuid.UUID, case: uuid.UUID, refs: list[Ref]
) -> tuple[list[Ref], list[Rejected]]:
    valid: list[Ref] = []
    rejected: list[Rejected] = []
    for ref in refs:
        reason = await _one(s, org, case, ref)
        if reason is None:
            valid.append(ref)
        else:
            rejected.append(Rejected(ref, reason))
    return valid, rejected
