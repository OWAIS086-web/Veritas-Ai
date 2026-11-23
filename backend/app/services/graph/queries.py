"""Graph reads for the API. Every query filters organization_id (RLS is the backstop), and
entities or relationships of deleted cases or other organizations are a 404."""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.models import (
    Case,
    Document,
    Entity,
    EntityMention,
    EvidenceItem,
    ExtractedField,
    Finding,
    OutboxEvent,
    Relationship,
)
from app.schemas.graph import (
    EdgeEvidenceOut,
    EntityOut,
    GraphEdgeOut,
    GraphNodeOut,
    GraphOut,
    MentionOut,
    RelationshipOut,
)
from app.services.cases.service import get_case
from app.services.graph.projection import CaseGraph
from app.services.graph.service import case_graph_from_postgres, filter_graph

logger = get_logger(__name__)


class GraphReader(Protocol):
    async def read_case(self, org: uuid.UUID, case_id: uuid.UUID) -> CaseGraph: ...


async def _sync_pending(s: AsyncSession, org: uuid.UUID, case_id: uuid.UUID) -> bool:
    found = await s.scalar(
        select(OutboxEvent.id)
        .where(
            OutboxEvent.organization_id == org,
            OutboxEvent.status.in_(("pending", "processing")),
            OutboxEvent.payload["case_id"].astext == str(case_id),
        )
        .limit(1)
    )
    return found is not None


async def case_graph(
    s: AsyncSession,
    reader: GraphReader | None,
    org: uuid.UUID,
    case_id: uuid.UUID,
    types: set[str] | None,
    q: str | None,
) -> GraphOut:
    await get_case(s, org, case_id)
    graph: CaseGraph | None = None
    source = "postgres"
    if reader is not None and not await _sync_pending(s, org, case_id):
        try:
            graph = await reader.read_case(org, case_id)
            source = "neo4j"
        except Exception as exc:
            logger.warning("graph_read_fallback", extra={"error": type(exc).__name__})
    if graph is None:
        graph = await case_graph_from_postgres(s, org, case_id)
    shown = filter_graph(graph, types, q)
    return GraphOut(
        nodes=[
            GraphNodeOut(
                id=n.id,
                kind=n.kind,
                type=n.type,
                label=n.label,
                properties=n.properties,
            )
            for n in shown.nodes
        ],
        edges=[
            GraphEdgeOut(
                id=e.id,
                type=e.type,
                source=e.source_id,
                target=e.target_id,
                evidence_ids=e.evidence_ids,
                finding_id=e.finding_id,
                properties=e.properties,
            )
            for e in shown.edges
        ],
        source=source,
        total_nodes=len(graph.nodes),
        total_edges=len(graph.edges),
    )


async def _entity(s: AsyncSession, org: uuid.UUID, entity_id: uuid.UUID) -> Entity:
    found = await s.scalar(
        select(Entity)
        .join(Case, Case.id == Entity.case_id)
        .where(Entity.id == entity_id, Entity.organization_id == org, Case.deleted_at.is_(None))
    )
    if found is None:
        raise NotFoundError("Entity not found.")
    return found


async def entity(s: AsyncSession, org: uuid.UUID, entity_id: uuid.UUID) -> EntityOut:
    e = await _entity(s, org, entity_id)
    rows = (
        await s.execute(
            select(EntityMention, Document.original_filename)
            .join(Document, Document.id == EntityMention.document_id)
            .where(EntityMention.organization_id == org, EntityMention.entity_id == e.id)
            .order_by(Document.original_filename, EntityMention.field_name)
        )
    ).all()
    out = EntityOut.model_validate(e)
    return out.model_copy(
        update={
            "mentions": [
                MentionOut.model_validate(m).model_copy(update={"document_filename": name})
                for m, name in rows
            ]
        }
    )


async def _labels(s: AsyncSession, org: uuid.UUID, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    labels: dict[uuid.UUID, str] = {}
    if not ids:
        return labels
    for i, name in await s.execute(
        select(Document.id, Document.original_filename).where(
            Document.organization_id == org, Document.id.in_(ids)
        )
    ):
        labels[i] = name
    for i, name in await s.execute(
        select(Entity.id, Entity.canonical_name).where(
            Entity.organization_id == org, Entity.id.in_(ids)
        )
    ):
        labels[i] = name
    for i, name in await s.execute(
        select(Finding.id, Finding.title).where(Finding.organization_id == org, Finding.id.in_(ids))
    ):
        labels[i] = name
    return labels


def _rel_out(r: Relationship, labels: dict[uuid.UUID, str]) -> RelationshipOut:
    return RelationshipOut(
        id=r.id,
        type=r.type,
        source_kind=r.source_kind,
        source_id=r.source_id,
        source_label=labels.get(r.source_id, ""),
        target_kind=r.target_kind,
        target_id=r.target_id,
        target_label=labels.get(r.target_id, ""),
        evidence_ids=sorted(r.evidence_ids, key=str),
        finding_id=r.finding_id,
        properties=dict(r.properties),
    )


async def entity_relationships(
    s: AsyncSession, org: uuid.UUID, entity_id: uuid.UUID
) -> list[RelationshipOut]:
    e = await _entity(s, org, entity_id)
    rows = list(
        await s.scalars(
            select(Relationship)
            .where(
                Relationship.organization_id == org,
                Relationship.case_id == e.case_id,
                or_(Relationship.source_id == e.id, Relationship.target_id == e.id),
            )
            .order_by(Relationship.type, Relationship.id)
        )
    )
    labels = await _labels(s, org, {i for r in rows for i in (r.source_id, r.target_id)})
    return [_rel_out(r, labels) for r in rows]


async def relationship_evidence(
    s: AsyncSession, org: uuid.UUID, relationship_id: uuid.UUID
) -> list[EdgeEvidenceOut]:
    r = await s.scalar(
        select(Relationship)
        .join(Case, Case.id == Relationship.case_id)
        .where(
            Relationship.id == relationship_id,
            Relationship.organization_id == org,
            Case.deleted_at.is_(None),
        )
    )
    if r is None:
        raise NotFoundError("Relationship not found.")
    ids = list(r.evidence_ids)
    out: list[EdgeEvidenceOut] = []
    for f, name, doc_type in await s.execute(
        select(ExtractedField, Document.original_filename, Document.doc_type)
        .join(Document, Document.id == ExtractedField.document_id)
        .where(ExtractedField.organization_id == org, ExtractedField.id.in_(ids))
    ):
        out.append(_evidence_out("extracted_field", f.id, f.document_id, name, doc_type, f.id, f))
    for e, name, doc_type in await s.execute(
        select(EvidenceItem, Document.original_filename, Document.doc_type)
        .join(Document, Document.id == EvidenceItem.document_id)
        .where(EvidenceItem.organization_id == org, EvidenceItem.id.in_(ids))
    ):
        out.append(
            _evidence_out(
                "evidence_item", e.id, e.document_id, name, doc_type, e.extracted_field_id, e
            )
        )
    out.sort(key=lambda x: (x.document_filename, x.field_name, str(x.id)))
    return out


def _evidence_out(
    kind: str,
    id_: uuid.UUID,
    document_id: uuid.UUID,
    filename: str,
    doc_type: str | None,
    field_id: uuid.UUID | None,
    row: Any,
) -> EdgeEvidenceOut:
    name = row.name if kind == "extracted_field" else row.field_name
    return EdgeEvidenceOut(
        id=id_,
        kind=kind,
        document_id=document_id,
        document_filename=filename,
        doc_type=doc_type,
        extracted_field_id=field_id,
        field_name=name,
        value=row.value,
        page_number=row.page_number,
        bbox=row.bbox,
        location=row.location,
        confidence=row.confidence,
    )
