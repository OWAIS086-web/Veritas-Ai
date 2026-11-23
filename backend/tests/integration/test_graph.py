# Req: evidence-knowledge-graph 1.1-1.2, 2.1-2.3, 3.1-3.3, 4.1-4.2
"""Evidence graph on the real pipeline output: Postgres rows with enforced evidence, the
outbox sync into a real Neo4j (own namespace), fallback, reconcile and tenant isolation."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from app.core.db import session_scope, set_tenant, tenant_session
from app.integrations.graph.neo4j_store import Neo4jStore, make_store
from app.models import Entity, EvidenceItem, ExtractedField, OutboxEvent, Relationship
from app.services.graph.projection import CaseGraph
from app.services.graph.service import case_graph_from_postgres
from app.services.graph.sync import outbox_health, process_outbox, reconcile
from tests.integration.conftest import register
from tests.integration.test_findings import Processed, _process

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
async def demo(app: Any) -> AsyncIterator[Processed]:
    transport = httpx.ASGITransport(app=app, client=("10.9.8.7", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield await _process(c)


@pytest.fixture
async def store(app_env: None) -> AsyncIterator[Neo4jStore]:
    s = make_store()
    await s.ensure_schema()
    yield s
    await s.close()


class BrokenStore:
    """Stands in for an unreachable Neo4j."""

    async def replace_case(self, org: uuid.UUID, case_id: uuid.UUID, graph: CaseGraph) -> None:
        raise ConnectionError("neo4j unreachable")

    async def read_case(self, org: uuid.UUID, case_id: uuid.UUID) -> CaseGraph:
        raise ConnectionError("neo4j unreachable")

    async def counts(self, org: uuid.UUID, case_id: uuid.UUID) -> tuple[int, int]:
        raise ConnectionError("neo4j unreachable")

    async def case_keys(self) -> set[tuple[uuid.UUID, uuid.UUID]]:
        raise ConnectionError("neo4j unreachable")


async def _graph(client: httpx.AsyncClient, p: Processed, **params: str) -> httpx.Response:
    resp = await client.get(
        f"/api/v1/cases/{p.case_id}/graph", headers=p.acct.headers, params=params
    )
    assert resp.status_code == 200, resp.text
    return resp


async def _drain(store: Any) -> dict[str, int]:
    total = {"done": 0, "retry": 0, "dead": 0}
    while True:
        r = await process_outbox(store)
        for k in total:
            total[k] += r[k]
        if sum(r.values()) == 0:
            return total


@pytest.mark.slow
async def test_demo_case_graph_is_backed_by_evidence(
    client: httpx.AsyncClient, demo: Processed
) -> None:
    org, case_id = demo.acct.organization_id, uuid.UUID(demo.case_id)
    async with tenant_session(org) as s:
        entities = list(await s.scalars(select(Entity).where(Entity.case_id == case_id)))
        rels = list(await s.scalars(select(Relationship).where(Relationship.case_id == case_id)))
        fields = {f.id: f for f in await s.scalars(select(ExtractedField))}
        items = set(await s.scalars(select(EvidenceItem.id)))
        pending = await s.scalar(
            select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status == "pending")
        )
    orgs = [e for e in entities if e.type == "organization"]
    assert sorted(e.canonical_name for e in orgs) == [
        "ABC Imports Inc.",
        "Global Trading Ltd",
        "Meridian Marine Insurance Co.",
        "Pacific Harbour Bank",
    ]
    # Printed on the documents: the PO's two addresses, and the goods on the insurance
    # certificate and the bill of lading (one product).
    assert sorted(e.type for e in entities if e.type in {"address", "product"}) == [
        "address",
        "address",
        "product",
    ]
    belongs = [r for r in rels if r.type == "BELONGS_TO"]
    assert len(belongs) == 2 and all(len(r.evidence_ids) == 2 for r in belongs)
    supplier = next(e for e in orgs if e.canonical_name == "Global Trading Ltd")
    assert supplier.status == "resolved" and supplier.mention_count == 7
    assert [e.normalized_name for e in entities if e.type == "shipment"] == ["SHIP2049"]
    # Every relationship cites real fields or evidence items of this organization.
    for r in rels:
        assert r.evidence_ids and all(i in fields or i in items for i in r.evidence_ids)
    types = [r.type for r in rels]
    assert types.count("CONTRADICTS") == 6 and types.count("SUPPORTS") == 5
    assert all(r.finding_id for r in rels if r.type == "CONTRADICTS")
    assert pending and pending >= 1  # the outbox row was written with the rebuild

    # While the sync is pending, the API serves the same rows from Postgres and says so.
    resp = await _graph(client, demo)
    body = resp.json()
    assert resp.headers["X-Graph-Source"] == "postgres" and body["source"] == "postgres"
    labels = {n["label"]: n for n in body["nodes"]}
    invoice = labels["02_commercial_invoice.pdf"]["id"]
    customs = labels["03_customs_declaration.pdf"]["id"]
    edges = body["edges"]
    assert any(
        e["type"] == "ISSUED_BY" and e["source"] == invoice and e["target"] == str(supplier.id)
        for e in edges
    )
    assert any(e["type"] == "SHIPPED_UNDER" and e["source"] == invoice for e in edges)
    contradicts = next(
        e
        for e in edges
        if e["type"] == "CONTRADICTS" and {e["source"], e["target"]} == {invoice, customs}
    )
    findings = (
        await client.get(f"/api/v1/cases/{demo.case_id}/findings", headers=demo.acct.headers)
    ).json()
    assert contradicts["finding_id"] == findings[0]["id"]

    evidence = (
        await client.get(
            f"/api/v1/relationships/{contradicts['id']}/evidence", headers=demo.acct.headers
        )
    ).json()
    assert sorted(e["value"] for e in evidence) == ["USD 48,000.00", "USD 68,000.00"]
    assert {e["kind"] for e in evidence} == {"evidence_item"}
    assert next(e for e in evidence if e["value"] == "USD 68,000.00")["page_number"] == 2


@pytest.mark.slow
async def test_outbox_syncs_into_neo4j_and_reads_match_postgres(
    client: httpx.AsyncClient, demo: Processed, store: Neo4jStore
) -> None:
    result = await _drain(store)
    assert result["done"] >= 1 and result["dead"] == 0
    org, case_id = demo.acct.organization_id, uuid.UUID(demo.case_id)
    async with tenant_session(org) as s:
        expected = await case_graph_from_postgres(s, org, case_id)
    from_neo4j = await store.read_case(org, case_id)
    assert sorted(str(n.id) for n in from_neo4j.nodes) == sorted(str(n.id) for n in expected.nodes)
    assert sorted((str(e.id), tuple(map(str, e.evidence_ids))) for e in from_neo4j.edges) == sorted(
        (str(e.id), tuple(map(str, e.evidence_ids))) for e in expected.edges
    )
    resp = await _graph(client, demo)
    assert resp.headers["X-Graph-Source"] == "neo4j"
    assert len(resp.json()["edges"]) == len(expected.edges)

    filtered = (await _graph(client, demo, types="document")).json()
    assert {n["kind"] for n in filtered["nodes"]} == {"document"}
    assert all(e["type"] in {"REFERENCES", "CONTRADICTS"} for e in filtered["edges"])
    searched = (await _graph(client, demo, q="global trading")).json()
    assert any(n["label"] == "Global Trading Ltd" for n in searched["nodes"])


@pytest.mark.slow
async def test_rebuild_keeps_ids_and_neo4j_outage_recovers(
    client: httpx.AsyncClient, demo: Processed, store: Neo4jStore
) -> None:
    org, case_id = demo.acct.organization_id, uuid.UUID(demo.case_id)
    async with tenant_session(org) as s:
        before = sorted(
            str(i)
            for i in await s.scalars(select(Relationship.id).where(Relationship.case_id == case_id))
        )
    resp = await client.post(
        f"/api/v1/cases/{demo.case_id}/graph/rebuild", headers=demo.acct.headers
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["relationships"] == len(before)
    async with tenant_session(org) as s:
        after = sorted(
            str(i)
            for i in await s.scalars(select(Relationship.id).where(Relationship.case_id == case_id))
        )
    assert after == before

    # Neo4j down: the row stays pending with a backoff and the API keeps serving Postgres.
    broken = await process_outbox(BrokenStore())
    assert broken["retry"] >= 1 and broken["dead"] == 0
    async with tenant_session(org) as s:
        rows = list(await s.scalars(select(OutboxEvent).where(OutboxEvent.status == "pending")))
        assert rows and all(r.attempts >= 1 and r.last_error for r in rows)
        await s.execute(
            update(OutboxEvent)
            .where(OutboxEvent.status == "pending")
            .values(available_at=func.now())
        )
    from app.api.v1.graph import graph_reader

    client_app = client._transport.app  # type: ignore[attr-defined]
    client_app.dependency_overrides[graph_reader] = lambda: BrokenStore()
    try:
        assert (await _graph(client, demo)).headers["X-Graph-Source"] == "postgres"
    finally:
        client_app.dependency_overrides.clear()
    health = await outbox_health()
    assert health["pending"] >= 1

    # Recovery: the next run applies the pending rows.
    assert (await _drain(store))["done"] >= 1
    async with tenant_session(org) as s:
        expected = await case_graph_from_postgres(s, org, case_id)
    assert await store.counts(org, case_id) == (len(expected.nodes), len(expected.edges))


@pytest.mark.slow
async def test_reconcile_repairs_drift_and_removes_deleted_cases(
    client: httpx.AsyncClient, demo: Processed, store: Neo4jStore
) -> None:
    org, case_id = demo.acct.organization_id, uuid.UUID(demo.case_id)
    await _drain(store)
    await store.replace_case(org, case_id, CaseGraph([], []))  # simulate drift
    assert (await reconcile(store))["queued"] >= 1
    await _drain(store)
    async with tenant_session(org) as s:
        expected = await case_graph_from_postgres(s, org, case_id)
    assert await store.counts(org, case_id) == (len(expected.nodes), len(expected.edges))

    # A deleted case's subgraph is removed from Neo4j.
    acct = demo.acct
    other = await _process(client, ["05_payment_receipt.pdf"])
    await _drain(store)
    other_case = uuid.UUID(other.case_id)
    assert (await store.counts(other.acct.organization_id, other_case))[0] > 0
    deleted = await client.delete(f"/api/v1/cases/{other.case_id}", headers=other.acct.headers)
    assert deleted.status_code == 204
    assert (await reconcile(store))["removed"] >= 1
    assert await store.counts(other.acct.organization_id, other_case) == (0, 0)
    assert acct.organization_id != other.acct.organization_id


async def test_a_dead_row_is_reported_after_max_attempts(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    case = (
        await client.post("/api/v1/cases", headers=acct.headers, json={"title": "Dead row"})
    ).json()
    async with tenant_session(acct.organization_id) as s:
        s.add(
            OutboxEvent(
                organization_id=acct.organization_id,
                target="neo4j",
                op="case.replace",
                payload={"case_id": case["id"]},
                status="pending",
                attempts=4,
            )
        )
    result = await process_outbox(BrokenStore())
    assert result["dead"] >= 1
    assert (await outbox_health())["dead"] >= 1
    health = (await client.get("/api/v1/system/health")).json()
    assert health["graph"]["outbox_dead"] >= 1
    assert health["status"] == "ok"  # the graph is optional; the API still serves Postgres


async def test_database_refuses_relationships_without_real_evidence(
    client: httpx.AsyncClient,
) -> None:
    acct = await register(client)
    case = (
        await client.post("/api/v1/cases", headers=acct.headers, json={"title": "Rule 3"})
    ).json()
    sql = (
        "INSERT INTO relationships (id, organization_id, case_id, type, source_kind, source_id,"
        " target_kind, target_id, evidence_ids, finding_id, properties, created_at) VALUES"
        " (gen_random_uuid(), :org, :case, :type, 'document', gen_random_uuid(), 'entity',"
        " gen_random_uuid(), :ids, NULL, '{}'::jsonb, now())"
    )
    cases: list[tuple[str, list[uuid.UUID], str]] = [
        ("ISSUED_BY", [], "evidence_required"),
        ("ISSUED_BY", [uuid.uuid4()], "relationship_evidence_not_found"),
        ("CONTRADICTS", [uuid.uuid4()], "contradicts_has_finding|relationship_evidence"),
    ]
    for type_, ids, message in cases:
        with pytest.raises(DBAPIError, match=message):
            async with session_scope() as s:
                await set_tenant(s, acct.organization_id)
                await s.execute(
                    text(sql),
                    {"org": acct.organization_id, "case": case["id"], "type": type_, "ids": ids},
                )


@pytest.mark.slow
async def test_entities_and_graph_are_isolated_between_organizations(
    client: httpx.AsyncClient, demo: Processed, store: Neo4jStore
) -> None:
    headers = demo.acct.headers
    body = (await _graph(client, demo)).json()
    supplier = next(n for n in body["nodes"] if n["label"] == "Global Trading Ltd")
    entity = (await client.get(f"/api/v1/entities/{supplier['id']}", headers=headers)).json()
    assert entity["mention_count"] == 7 and len(entity["mentions"]) == 7
    assert {m["value"] for m in entity["mentions"]} == {
        "Global Trading Ltd",
        "GLOBAL TRADING LIMITED",
    }
    rels = (
        await client.get(f"/api/v1/entities/{supplier['id']}/relationships", headers=headers)
    ).json()
    assert any(
        r["type"] == "ISSUED_BY" and r["source_label"] == "02_commercial_invoice.pdf" for r in rels
    )
    edge_id = rels[0]["id"]

    outsider = await register(client, org_name="Graph Outsider")
    for method, path in [
        ("GET", f"/api/v1/cases/{demo.case_id}/graph"),
        ("POST", f"/api/v1/cases/{demo.case_id}/graph/rebuild"),
        ("GET", f"/api/v1/entities/{supplier['id']}"),
        ("GET", f"/api/v1/entities/{supplier['id']}/relationships"),
        ("GET", f"/api/v1/relationships/{edge_id}/evidence"),
    ]:
        resp = await client.request(method, path, headers=outsider.headers)
        assert resp.status_code == 404, f"{method} {path}: {resp.status_code}"
    # Neo4j queries are scoped too: another organization's id reads an empty graph.
    assert await store.counts(outsider.organization_id, uuid.UUID(demo.case_id)) == (0, 0)
    for table in ("entities", "entity_mentions", "relationships", "outbox"):
        async with session_scope() as s:
            await set_tenant(s, outsider.organization_id)
            seen = (await s.scalars(text(f"SELECT organization_id FROM {table}"))).all()  # noqa: S608
        assert seen == [], table
