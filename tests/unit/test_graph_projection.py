"""Graph projection: the demo edges, the evidence rule and determinism."""

from __future__ import annotations

import random
import uuid
from dataclasses import replace

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.comparison.engine import evaluate_all
from app.services.entity_resolution.resolve import resolve
from app.services.graph.projection import CaseGraph, EvidenceRef, FindingRef, project
from tests.unit.comparison_fixtures import CTX, Case, demo_case

CASE = uuid.UUID("00000000-0000-0000-0000-0000000a11ce")


def _findings(c: Case) -> list[FindingRef]:
    """Findings as the rule engine produces them, with an evidence-item id per citation."""
    refs = []
    for d in evaluate_all(c.fields, c.docs, CTX).drafts:
        evidence = tuple(
            EvidenceRef(
                uuid.uuid5(CASE, f"{d.key}:{e.obs.field_id}"),
                e.obs.document_id,
                e.role,
                e.obs.normalized,
            )
            for e in d.evidence
        )
        refs.append(
            FindingRef(uuid.uuid5(CASE, d.key), d.type, d.title, d.severity, "new", evidence)
        )
    return refs


def _graph(c: Case) -> tuple[CaseGraph, list[FindingRef]]:
    findings = _findings(c)
    entities = resolve(CASE, c.fields, 0.95, 0.85)
    return project(CASE, c.docs, c.fields, entities, findings), findings


def _doc(c: Case, doc_type: str) -> uuid.UUID:
    return next(d.id for d in c.docs if d.doc_type == doc_type)


def test_demo_graph_has_the_expected_evidence_backed_edges() -> None:
    c = demo_case()
    graph, findings = _graph(c)
    nodes = {n.id: n for n in graph.nodes}
    by = {(e.type, e.source_id, e.target_id): e for e in graph.edges}
    invoice, customs = _doc(c, "commercial_invoice"), _doc(c, "customs_declaration")
    supplier = next(
        n for n in graph.nodes if n.kind == "entity" and n.label == "Global Trading Ltd"
    )
    shipment = next(n for n in graph.nodes if n.kind == "entity" and n.type == "shipment")

    issued = by[("ISSUED_BY", invoice, supplier.id)]
    field_ids = {f.field_id: f for f in c.fields}
    assert [field_ids[i].name for i in issued.evidence_ids] == ["supplier"]
    assert ("SHIPPED_UNDER", invoice, shipment.id) in by
    # The customs declaration names the invoice it covers.
    cites = by[("REFERENCES", customs, invoice)]
    assert sorted(field_ids[i].name for i in cites.evidence_ids) == [
        "document_number",
        "invoice_reference",
    ]
    # The customs value contradicts the invoice total, under the financial finding.
    [finding] = findings
    contradicts = [e for e in graph.edges if e.type == "CONTRADICTS"]
    assert len(contradicts) == 6  # three documents at 48,000 against two at 68,000
    assert {e.finding_id for e in contradicts} == {finding.id}
    pair = next(e for e in contradicts if {e.source_id, e.target_id} == {invoice, customs})
    evidence_ids = {ev.id for ev in finding.evidence}
    assert len(pair.evidence_ids) == 2 and set(pair.evidence_ids) <= evidence_ids
    supports = [e for e in graph.edges if e.type == "SUPPORTS"]
    assert len(supports) == 5 and all(e.target_id == finding.id for e in supports)
    # The exporter spelling on the customs declaration resolves to the same supplier node.
    assert ("ASSOCIATED_WITH", customs, supplier.id) in by
    assert nodes[finding.id].kind == "finding"


def test_no_contradiction_between_documents_that_agree() -> None:
    c = demo_case()
    graph, _ = _graph(c)
    po, invoice = _doc(c, "purchase_order"), _doc(c, "commercial_invoice")
    assert not any(
        e.type == "CONTRADICTS" and {e.source_id, e.target_id} == {po, invoice} for e in graph.edges
    )


@settings(max_examples=25)
@given(st.randoms(), st.lists(st.sampled_from(range(7)), unique=True, max_size=6))
def test_every_edge_has_resolvable_evidence_and_known_ends(
    rnd: random.Random, drop: list[int]
) -> None:
    c = demo_case()
    removed = {c.docs[i].id for i in drop}
    c.docs = [d for d in c.docs if d.id not in removed]
    c.fields = [f for f in c.fields if f.document_id not in removed]
    graph, findings = _graph(c)
    shuffled = Case()
    shuffled.docs, shuffled.fields = list(c.docs), [replace(f) for f in c.fields]
    rnd.shuffle(shuffled.fields)
    rnd.shuffle(shuffled.docs)
    again, _ = _graph(shuffled)
    assert [(e.id, e.evidence_ids) for e in again.edges] == [
        (e.id, e.evidence_ids) for e in graph.edges
    ]

    known = {f.field_id for f in c.fields} | {ev.id for f in findings for ev in f.evidence}
    node_ids = {n.id for n in graph.nodes}
    for e in graph.edges:
        assert e.evidence_ids and set(e.evidence_ids) <= known
        assert e.source_id in node_ids and e.target_id in node_ids
        assert e.type != "CONTRADICTS" or e.finding_id is not None


def test_filter_by_type_and_search_keeps_neighbours_and_only_inner_edges() -> None:
    from app.services.graph.service import filter_graph

    c = demo_case()
    graph, _ = _graph(c)
    entities_only = filter_graph(graph, {"entity"}, None)
    assert {n.kind for n in entities_only.nodes} == {"entity"}
    assert entities_only.edges == []  # every edge touches a document or a finding

    found = filter_graph(graph, None, "customs")
    labels = {n.label for n in found.nodes}
    assert "03_customs_declaration.pdf" in labels
    assert "Global Trading Ltd" in labels  # a neighbour of the match stays visible
    keep = {n.id for n in found.nodes}
    assert all(e.source_id in keep and e.target_id in keep for e in found.edges)
    assert filter_graph(graph, None, "no-such-node").nodes == []
