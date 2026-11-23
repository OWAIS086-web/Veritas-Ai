"""Evidence graph: case graph, entities, relationship evidence, rebuild."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, request_meta, require_permission
from app.core.config import get_settings
from app.integrations.graph.neo4j_store import get_store
from app.schemas.common import PROBLEM_RESPONSES
from app.schemas.graph import EdgeEvidenceOut, EntityOut, GraphOut, RebuildOut, RelationshipOut
from app.services.audit import service as audit
from app.services.cases.service import get_case
from app.services.graph import queries
from app.services.graph.queries import GraphReader
from app.services.graph.service import rebuild_case_graph
from app.services.identity.principal import Principal, RequestMeta
from app.workers.dispatch import enqueue_graph_sync

router = APIRouter(tags=["graph"], responses=PROBLEM_RESPONSES)


def graph_reader() -> GraphReader | None:
    """Neo4j when configured; None means "serve from Postgres"."""
    return get_store() if get_settings().neo4j_password else None


@router.get(
    "/cases/{case_id}/graph",
    response_model=GraphOut,
    summary="Evidence graph of a case (X-Graph-Source tells where it was read from)",
)
async def case_graph(
    case_id: uuid.UUID,
    response: Response,
    types: str | None = Query(
        None,
        max_length=200,
        pattern=r"^[a-z_]+(,[a-z_]+)*$",
        description="Comma-separated node kinds or types, e.g. document,organization",
    ),
    q: str | None = Query(None, max_length=100, description="Label search; keeps neighbours"),
    principal: Principal = Depends(require_permission("graph:read")),
    session: AsyncSession = Depends(db_session),
    reader: GraphReader | None = Depends(graph_reader),
) -> GraphOut:
    selected = set(types.split(",")) if types else None
    out = await queries.case_graph(session, reader, principal.organization_id, case_id, selected, q)
    response.headers["X-Graph-Source"] = out.source
    return out


@router.post(
    "/cases/{case_id}/graph/rebuild",
    response_model=RebuildOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Rebuild the case graph from Postgres and queue the Neo4j sync",
)
async def rebuild(
    case_id: uuid.UUID,
    background: BackgroundTasks,
    principal: Principal = Depends(require_permission("graph:rebuild")),
    session: AsyncSession = Depends(db_session),
    meta: RequestMeta = Depends(request_meta),
) -> RebuildOut:
    await get_case(session, principal.organization_id, case_id)
    counts = await rebuild_case_graph(session, principal.organization_id, case_id)
    await audit.record(
        session,
        "graph.rebuild",
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        resource_type="case",
        resource_id=case_id,
        meta=meta,
        metadata=counts,
    )
    background.add_task(enqueue_graph_sync)
    return RebuildOut(**counts)


@router.get("/entities/{entity_id}", response_model=EntityOut, summary="Entity with its mentions")
async def get_entity(
    entity_id: uuid.UUID,
    principal: Principal = Depends(require_permission("graph:read")),
    session: AsyncSession = Depends(db_session),
) -> EntityOut:
    return await queries.entity(session, principal.organization_id, entity_id)


@router.get(
    "/entities/{entity_id}/relationships",
    response_model=list[RelationshipOut],
    summary="Relationships of an entity",
)
async def entity_relationships(
    entity_id: uuid.UUID,
    principal: Principal = Depends(require_permission("graph:read")),
    session: AsyncSession = Depends(db_session),
) -> list[RelationshipOut]:
    return await queries.entity_relationships(session, principal.organization_id, entity_id)


@router.get(
    "/relationships/{relationship_id}/evidence",
    response_model=list[EdgeEvidenceOut],
    summary="The extracted fields and evidence items behind a relationship",
)
async def relationship_evidence(
    relationship_id: uuid.UUID,
    principal: Principal = Depends(require_permission("graph:read")),
    session: AsyncSession = Depends(db_session),
) -> list[EdgeEvidenceOut]:
    return await queries.relationship_evidence(session, principal.organization_id, relationship_id)
