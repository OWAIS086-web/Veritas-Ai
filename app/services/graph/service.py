"""Postgres side of the evidence graph: rebuild a case's derived rows, read them back.

`rebuild_case_graph` runs inside the caller's transaction (the comparison's), deletes the
case's entities, mentions and relationships, inserts the freshly projected ones, and writes
an outbox row in the same transaction. The Neo4j copy is updated from that row later.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import (
    Case,
    Document,
    DocumentStatus,
    Entity,
    EntityMention,
    EvidenceItem,
    Finding,
    OutboxEvent,
    Relationship,
)
from app.services.comparison.model import DocInfo
from app.services.comparison.persist import load_inputs
from app.services.entity_resolution.resolve import resolve
from app.services.graph.projection import (
    CaseGraph,
    EvidenceRef,
    FindingRef,
    GraphEdge,
    document_node,
    entity_node,
    finding_node,
    project,
)

SYNC_OP = "case.replace"


async def finding_refs(s: AsyncSession, org: uuid.UUID, case_id: uuid.UUID) -> list[FindingRef]:
    rows = list(
        await s.scalars(
            select(Finding)
            .where(Finding.organization_id == org, Finding.case_id == case_id, Finding.active)
            .order_by(Finding.created_at, Finding.id)
        )
    )
    evidence: dict[uuid.UUID, list[EvidenceRef]] = defaultdict(list)
    if rows:
        for e in await s.scalars(
            select(EvidenceItem)
            .where(
                EvidenceItem.organization_id == org,
                EvidenceItem.finding_id.in_([f.id for f in rows]),
            )
            .order_by(EvidenceItem.id)
        ):
            evidence[e.finding_id].append(
                EvidenceRef(e.id, e.document_id, e.role, e.normalized_value)
            )
    return [
        FindingRef(f.id, f.type, f.title, f.severity, f.status, tuple(evidence[f.id])) for f in rows
    ]


async def enqueue_sync(s: AsyncSession, org: uuid.UUID, case_id: uuid.UUID) -> None:
    s.add(
        OutboxEvent(
            organization_id=org,
            target="neo4j",
            op=SYNC_OP,
            payload={"case_id": str(case_id)},
            status="pending",
            attempts=0,
        )
    )


async def rebuild_case_graph(s: AsyncSession, org: uuid.UUID, case_id: uuid.UUID) -> dict[str, int]:
    settings = get_settings()
    docs, fields, _ = await load_inputs(s, org, case_id)
    findings = await finding_refs(s, org, case_id)
    entities = resolve(
        case_id, fields, settings.entity_merge_threshold, settings.name_similarity_threshold
    )
    graph = project(case_id, docs, fields, entities, findings)

    await s.execute(
        delete(Relationship).where(
            Relationship.organization_id == org, Relationship.case_id == case_id
        )
    )
    await s.execute(delete(Entity).where(Entity.organization_id == org, Entity.case_id == case_id))
    for e in entities:
        s.add(
            Entity(
                id=e.id,
                organization_id=org,
                case_id=case_id,
                type=e.type,
                canonical_name=e.canonical_name,
                normalized_name=e.normalized_name,
                confidence=e.confidence,
                status=e.status,
                mention_count=len(e.mentions),
                details={"similarity": e.similarity, "possible_duplicates": e.possible_duplicates},
            )
        )
    await s.flush()
    for e in entities:
        for m in e.mentions:
            s.add(
                EntityMention(
                    id=uuid.uuid5(e.id, str(m.field_id)),
                    organization_id=org,
                    entity_id=e.id,
                    extracted_field_id=m.field_id,
                    document_id=m.document_id,
                    field_name=m.name,
                    value=m.value,
                    page_number=m.page_number,
                    bbox=m.bbox,
                    location=m.location,
                    confidence=m.confidence,
                )
            )
    for edge in graph.edges:
        s.add(
            Relationship(
                id=edge.id,
                organization_id=org,
                case_id=case_id,
                type=edge.type,
                source_kind=edge.source_kind,
                source_id=edge.source_id,
                target_kind=edge.target_kind,
                target_id=edge.target_id,
                evidence_ids=edge.evidence_ids,
                finding_id=edge.finding_id,
                properties=edge.properties,
            )
        )
    await enqueue_sync(s, org, case_id)
    await s.flush()
    return {"entities": len(entities), "relationships": len(graph.edges)}


async def drop_document_edges(s: AsyncSession, org: uuid.UUID, document_id: uuid.UUID) -> None:
    """Called before a document's fields are replaced, so no relationship points at evidence
    that is about to be deleted. The comparison at the end of the job rebuilds the graph."""
    await s.execute(
        delete(Relationship).where(
            Relationship.organization_id == org,
            (Relationship.source_id == document_id) | (Relationship.target_id == document_id),
        )
    )


async def case_graph_from_postgres(
    s: AsyncSession, org: uuid.UUID, case_id: uuid.UUID
) -> CaseGraph:
    """The persisted graph of a live case (empty for a deleted or unknown case)."""
    live = await s.scalar(
        select(Case.id).where(
            Case.id == case_id, Case.organization_id == org, Case.deleted_at.is_(None)
        )
    )
    if live is None:
        return CaseGraph([], [])
    docs = await s.scalars(
        select(Document)
        .where(
            Document.organization_id == org,
            Document.case_id == case_id,
            Document.status == DocumentStatus.COMPLETED,
        )
        .order_by(Document.original_filename, Document.id)
    )
    nodes = [
        document_node(DocInfo(d.id, d.original_filename, d.doc_type, d.sha256, d.status))
        for d in docs
    ]
    for e in await s.scalars(
        select(Entity)
        .where(Entity.organization_id == org, Entity.case_id == case_id)
        .order_by(Entity.type, Entity.normalized_name)
    ):
        nodes.append(
            entity_node(e.id, e.type, e.canonical_name, e.status, e.mention_count, e.confidence)
        )
    nodes.extend(finding_node(f) for f in await finding_refs(s, org, case_id))
    known = {n.id for n in nodes}
    edges = [
        GraphEdge(
            r.id,
            r.type,
            r.source_kind,
            r.source_id,
            r.target_kind,
            r.target_id,
            sorted(r.evidence_ids, key=str),
            r.finding_id,
            dict(r.properties),
        )
        for r in await s.scalars(
            select(Relationship)
            .where(Relationship.organization_id == org, Relationship.case_id == case_id)
            .order_by(Relationship.type, Relationship.id)
        )
        if r.source_id in known and r.target_id in known
    ]
    return CaseGraph(nodes, edges)


def filter_graph(graph: CaseGraph, types: set[str] | None, q: str | None) -> CaseGraph:
    """Keep nodes whose kind or type is selected and whose label matches the search; keep
    edges whose two ends are kept."""
    needle = (q or "").casefold().strip()
    nodes = [
        n
        for n in graph.nodes
        if (not types or n.kind in types or n.type in types)
        and (not needle or needle in n.label.casefold())
    ]
    if needle:
        # A search keeps the matches and their direct neighbours, so the context stays visible.
        hits = {n.id for n in nodes}
        neighbours = {
            other
            for e in graph.edges
            for end, other in ((e.source_id, e.target_id), (e.target_id, e.source_id))
            if end in hits
        }
        allowed = {n.id for n in graph.nodes if not types or n.kind in types or n.type in types}
        nodes = [n for n in graph.nodes if n.id in hits or (n.id in neighbours and n.id in allowed)]
    keep = {n.id for n in nodes}
    return CaseGraph(nodes, [e for e in graph.edges if e.source_id in keep and e.target_id in keep])


def graph_counts(graph: CaseGraph) -> dict[str, Any]:
    return {"nodes": len(graph.nodes), "edges": len(graph.edges)}
