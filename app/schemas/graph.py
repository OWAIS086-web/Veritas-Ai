"""Evidence graph API contracts."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ApiModel

NodeKind = Literal["document", "entity", "finding"]


class GraphNodeOut(BaseModel):
    id: uuid.UUID
    kind: NodeKind
    type: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdgeOut(BaseModel):
    id: uuid.UUID
    type: str
    source: uuid.UUID
    target: uuid.UUID
    evidence_ids: list[uuid.UUID] = Field(
        description="extracted_fields or evidence_items rows this relationship is based on"
    )
    finding_id: uuid.UUID | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphOut(BaseModel):
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]
    source: Literal["neo4j", "postgres"] = Field(
        description="Where this graph was read from. Postgres is used while a sync is pending "
        "or when Neo4j is unavailable; both hold the same persisted rows."
    )
    total_nodes: int
    total_edges: int


class RebuildOut(BaseModel):
    entities: int
    relationships: int


class MentionOut(ApiModel):
    id: uuid.UUID
    extracted_field_id: uuid.UUID
    document_id: uuid.UUID
    document_filename: str = ""
    field_name: str
    value: str | None
    page_number: int | None
    bbox: list[float] | None
    location: str | None
    confidence: Decimal | None


class EntityOut(ApiModel):
    id: uuid.UUID
    case_id: uuid.UUID
    type: str
    canonical_name: str
    normalized_name: str
    confidence: Decimal | None
    status: Literal["resolved", "possible_duplicate"]
    mention_count: int
    details: dict[str, Any]
    mentions: list[MentionOut] = Field(default_factory=list)


class RelationshipOut(BaseModel):
    id: uuid.UUID
    type: str
    source_kind: str
    source_id: uuid.UUID
    source_label: str
    target_kind: str
    target_id: uuid.UUID
    target_label: str
    evidence_ids: list[uuid.UUID]
    finding_id: uuid.UUID | None
    properties: dict[str, Any]


class EdgeEvidenceOut(BaseModel):
    id: uuid.UUID
    kind: Literal["extracted_field", "evidence_item"]
    document_id: uuid.UUID
    document_filename: str
    doc_type: str | None
    extracted_field_id: uuid.UUID | None
    field_name: str
    value: str | None
    page_number: int | None
    bbox: list[float] | None
    location: str | None
    confidence: Decimal | None
