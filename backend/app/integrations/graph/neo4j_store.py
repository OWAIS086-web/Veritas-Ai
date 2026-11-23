"""Neo4j copy of the case graphs. Postgres stays the source of truth.

Cypher text is built only from the fixed label and relationship-type allowlists below; every
value is a bound parameter. Every node and edge carries `ns` (the deployment namespace),
`organization_id` and `case_id`, and every query filters on all three.
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from app.core.config import get_settings
from app.services.graph.projection import EDGE_TYPES, CaseGraph, GraphEdge, GraphNode

LABELS = {"document": "Document", "entity": "Entity", "finding": "Finding"}
BASE = "VeritasNode"
SCOPE = "{ns: $ns, organization_id: $org, case_id: $case}"
SCHEMA = [
    f"CREATE CONSTRAINT veritas_node_id IF NOT EXISTS FOR (n:{BASE}) REQUIRE n.id IS UNIQUE",
    f"CREATE INDEX veritas_node_scope IF NOT EXISTS FOR (n:{BASE}) "
    "ON (n.ns, n.organization_id, n.case_id)",
]


class GraphUnavailableError(Exception):
    """Neo4j could not be reached or answered with an error."""


def _scalar(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, list | tuple):
        return [str(v) for v in value]
    return value


def _unprefix(props: dict[str, Any]) -> dict[str, Any]:
    return {k[2:]: v for k, v in props.items() if k.startswith("p_")}


class Neo4jStore:
    def __init__(self, driver: AsyncDriver, namespace: str) -> None:
        self._driver = driver
        self._ns = namespace

    def _scope(self, org: uuid.UUID, case_id: uuid.UUID) -> dict[str, str]:
        return {"ns": self._ns, "org": str(org), "case": str(case_id)}

    def _stamp(self, org: uuid.UUID, case_id: uuid.UUID) -> dict[str, str]:
        return {"ns": self._ns, "organization_id": str(org), "case_id": str(case_id)}

    async def close(self) -> None:
        await self._driver.close()

    async def ensure_schema(self) -> None:
        try:
            async with self._driver.session() as session:
                for statement in SCHEMA:
                    await session.run(statement)
        except Exception as exc:
            raise GraphUnavailableError(type(exc).__name__) from exc

    async def ping(self) -> None:
        try:
            await self._driver.verify_connectivity()
        except Exception as exc:
            raise GraphUnavailableError(type(exc).__name__) from exc

    async def replace_case(self, org: uuid.UUID, case_id: uuid.UUID, graph: CaseGraph) -> None:
        """Replace the whole subgraph of one case in a single transaction."""
        scope, stamp = self._scope(org, case_id), self._stamp(org, case_id)
        nodes_by_label: dict[str, list[dict[str, Any]]] = {}
        for n in graph.nodes:
            nodes_by_label.setdefault(LABELS[n.kind], []).append(_node_row(n, stamp))
        edges_by_type: dict[str, list[dict[str, Any]]] = {}
        for e in graph.edges:
            if e.type not in EDGE_TYPES:
                raise ValueError(f"unknown relationship type {e.type!r}")
            edges_by_type.setdefault(e.type, []).append(
                {
                    "source": str(e.source_id),
                    "target": str(e.target_id),
                    "props": _edge_row(e, stamp),
                }
            )

        async def work(tx: Any) -> None:
            await tx.run(f"MATCH (n:{BASE} {SCOPE}) DETACH DELETE n", **scope)
            for label, rows in nodes_by_label.items():
                await tx.run(
                    f"UNWIND $rows AS row CREATE (n:{BASE}:{label}) SET n = row", rows=rows
                )
            for type_, rows in edges_by_type.items():
                await tx.run(
                    "UNWIND $rows AS row "
                    f"MATCH (a:{BASE} {{id: row.source, ns: $ns, "
                    "organization_id: $org, case_id: $case}) "
                    f"MATCH (b:{BASE} {{id: row.target, ns: $ns, "
                    "organization_id: $org, case_id: $case}) "
                    f"CREATE (a)-[r:{type_}]->(b) SET r = row.props",
                    rows=rows,
                    **scope,
                )

        try:
            async with self._driver.session() as session:
                await session.execute_write(work)
        except Exception as exc:
            raise GraphUnavailableError(type(exc).__name__) from exc

    async def read_case(self, org: uuid.UUID, case_id: uuid.UUID) -> CaseGraph:
        scope = self._scope(org, case_id)
        try:
            async with self._driver.session() as session:
                node_rows = await (
                    await session.run(
                        f"MATCH (n:{BASE} {SCOPE}) "
                        "RETURN properties(n) AS p ORDER BY n.kind, n.label, n.id",
                        parameters=scope,
                    )
                ).data()
                edge_rows = await (
                    await session.run(
                        f"MATCH (a:{BASE} {SCOPE})-[r]->(b:{BASE} {SCOPE}) "
                        "WHERE r.ns = $ns AND r.organization_id = $org AND r.case_id = $case "
                        "RETURN properties(r) AS p, type(r) AS t, a.id AS s, a.kind AS sk, "
                        "b.id AS d, b.kind AS dk ORDER BY t, r.id",
                        parameters=scope,
                    )
                ).data()
        except Exception as exc:
            raise GraphUnavailableError(type(exc).__name__) from exc
        nodes = [
            GraphNode(
                uuid.UUID(r["p"]["id"]),
                r["p"]["kind"],
                r["p"]["type"],
                r["p"]["label"],
                _unprefix(r["p"]),
            )
            for r in node_rows
        ]
        edges = [
            GraphEdge(
                uuid.UUID(r["p"]["id"]),
                r["t"],
                r["sk"],
                uuid.UUID(r["s"]),
                r["dk"],
                uuid.UUID(r["d"]),
                [uuid.UUID(i) for i in r["p"]["evidence_ids"]],
                uuid.UUID(r["p"]["finding_id"]) if r["p"].get("finding_id") else None,
                _unprefix(r["p"]),
            )
            for r in edge_rows
        ]
        return CaseGraph(nodes, edges)

    async def counts(self, org: uuid.UUID, case_id: uuid.UUID) -> tuple[int, int]:
        graph = await self.read_case(org, case_id)
        return len(graph.nodes), len(graph.edges)

    async def case_keys(self) -> set[tuple[uuid.UUID, uuid.UUID]]:
        """Every (organization, case) of this namespace present in Neo4j, for the reconciler."""
        try:
            async with self._driver.session() as session:
                rows = await (
                    await session.run(
                        f"MATCH (n:{BASE} {{ns: $ns}}) "
                        "RETURN DISTINCT n.organization_id AS o, n.case_id AS c",
                        parameters={"ns": self._ns},
                    )
                ).data()
        except Exception as exc:
            raise GraphUnavailableError(type(exc).__name__) from exc
        return {(uuid.UUID(r["o"]), uuid.UUID(r["c"])) for r in rows}


def _node_row(n: GraphNode, stamp: dict[str, str]) -> dict[str, Any]:
    props = {f"p_{k}": _scalar(v) for k, v in n.properties.items() if v is not None}
    return {**props, **stamp, "id": str(n.id), "kind": n.kind, "type": n.type, "label": n.label}


def _edge_row(e: GraphEdge, stamp: dict[str, str]) -> dict[str, Any]:
    props = {f"p_{k}": _scalar(v) for k, v in e.properties.items() if v is not None}
    return {
        **props,
        **stamp,
        "id": str(e.id),
        "evidence_ids": [str(i) for i in e.evidence_ids],
        "finding_id": str(e.finding_id) if e.finding_id else None,
    }


def make_store() -> Neo4jStore:
    s = get_settings()
    driver = AsyncGraphDatabase.driver(
        s.neo4j_uri,
        auth=(s.neo4j_user, s.neo4j_password),
        connection_timeout=s.neo4j_timeout_seconds,
        connection_acquisition_timeout=s.neo4j_timeout_seconds,
        max_transaction_retry_time=s.neo4j_timeout_seconds,
    )
    return Neo4jStore(driver, s.neo4j_namespace)


@lru_cache
def get_store() -> Neo4jStore:
    """One driver per API process (the driver keeps its own connection pool)."""
    return make_store()
