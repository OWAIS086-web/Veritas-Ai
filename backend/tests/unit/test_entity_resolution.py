"""Entity resolution (entity_resolution.resolve): demo outcome, thresholds, invariants."""

from __future__ import annotations

import random
import uuid
from dataclasses import replace
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from app.services.entity_resolution.resolve import ENTITY_FIELDS, entity_id, resolve
from tests.unit.comparison_fixtures import Case, demo_case

CASE = uuid.UUID("00000000-0000-0000-0000-00000000c0de")


def _resolve(c: Case, merge: float = 0.95, flag: float = 0.85):  # type: ignore[no-untyped-def]
    return resolve(CASE, c.fields, merge, flag)


def test_demo_case_resolves_supplier_variants_into_one_entity() -> None:
    entities = _resolve(demo_case())
    orgs = {e.normalized_name: e for e in entities if e.type == "organization"}
    assert set(orgs) == {"global trading", "abc imports"}
    supplier = orgs["global trading"]
    raw = {m.value for m in supplier.mentions}
    assert raw == {"Global Trading Ltd", "GLOBAL TRADING LIMITED"}
    assert supplier.canonical_name == "Global Trading Ltd"  # the most frequent spelling
    assert len({m.document_id for m in supplier.mentions}) == 7
    assert supplier.status == "resolved" and supplier.confidence == Decimal("1.000")
    [shipment] = [e for e in entities if e.type == "shipment"]
    assert shipment.normalized_name == "SHIP2049" and len(shipment.mentions) == 6
    assert supplier.id == entity_id(CASE, "organization", "global trading")


def test_close_names_are_flagged_not_merged_and_distant_names_stay_apart() -> None:
    c = Case()
    a, b, d = (
        c.doc("commercial_invoice", "a.pdf"),
        c.doc("bill_of_lading", "b.pdf"),
        c.doc("packing_list", "d.pdf"),
    )
    c.party(a, "supplier", "Global Trading Ltd")
    c.party(b, "supplier", "Global Tradings Ltd")  # similarity ~0.97 with a lower merge bar
    c.party(d, "supplier", "Global Shipping Partners")
    merged = _resolve(c, merge=0.9, flag=0.85)
    assert sorted(e.normalized_name for e in merged) == [
        "global shipping partners",
        "global trading",
    ]
    flagged = _resolve(c, merge=0.99, flag=0.85)
    by_name = {e.normalized_name: e for e in flagged}
    assert by_name["global trading"].status == "possible_duplicate"
    assert by_name["global tradings"].possible_duplicates == ["global trading"]
    assert by_name["global shipping partners"].status == "resolved"


def test_unmeasured_confidence_stays_null_and_uncertain_fields_are_ignored() -> None:
    c = Case()
    a, b = c.doc("commercial_invoice", "a.pdf"), c.doc("payment_receipt", "b.pdf")
    c.party(a, "buyer", "ABC Imports Inc.", confidence=None)
    c.party(b, "buyer", "ABC Imports Inc.")
    c.add(b, "supplier", None, None, "party", status="uncertain", reason="not_found")
    [buyer] = _resolve(c)
    assert buyer.confidence is None and len(buyer.mentions) == 2


party_names = st.sampled_from(
    [
        "Global Trading Ltd",
        "GLOBAL TRADING LIMITED",
        "ABC Imports Inc.",
        "Abc Imports",
        "Northwind Freight",
        "Meridian Marine Insurance Co.",
        "Global Traders",
    ]
)


@given(
    st.lists(
        st.tuples(st.sampled_from(sorted(ENTITY_FIELDS)), party_names), min_size=1, max_size=12
    ),
    st.randoms(),
)
def test_resolution_is_order_independent_and_partitions_the_mentions(
    mentions: list[tuple[str, str]], rnd: random.Random
) -> None:
    c = Case()
    for i, (name, value) in enumerate(mentions):
        doc = c.doc("commercial_invoice", f"d{i}.pdf")
        if name in {"shipment_reference", "bank_reference"}:
            c.ref(doc, name, value.replace(" ", "-")[:20])
        else:
            c.party(doc, name, value)
    first = _resolve(c)
    shuffled = replace_fields(c, rnd)
    second = _resolve(shuffled)
    assert [
        (e.id, e.normalized_name, sorted(str(m.field_id) for m in e.mentions)) for e in first
    ] == [(e.id, e.normalized_name, sorted(str(m.field_id) for m in e.mentions)) for e in second]
    seen = [m.field_id for e in first for m in e.mentions]
    assert len(seen) == len(set(seen)) == len(c.fields)
    # Mentions with the same normalized key always land in the same entity.
    key_to_entity: dict[tuple[str, str], uuid.UUID] = {}
    for e in first:
        for m in e.mentions:
            key = (e.type, str(m.normalized.get("key")))
            assert key_to_entity.setdefault(key, e.id) == e.id


def replace_fields(c: Case, rnd: random.Random) -> Case:
    out = Case()
    out.docs = list(c.docs)
    out.fields = [replace(f) for f in c.fields]
    rnd.shuffle(out.fields)
    return out


def test_addresses_products_and_banks_become_entities_with_evidence_backed_edges() -> None:
    from app.services.extraction.normalize import normalize_address, normalize_product
    from app.services.graph.projection import project

    c = Case()
    po = c.doc("purchase_order", "po.pdf")
    ins = c.doc("insurance_certificate", "ins.pdf")
    bl = c.doc("bill_of_lading", "bl.pdf")
    rc = c.doc("payment_receipt", "rc.pdf")
    supplier = c.party(po, "supplier", "Global Trading Ltd")
    addr_value = "Unit 7, 88 Harbour Road, Kowloon, Hong Kong"
    address = c.add(
        po,
        "supplier_address",
        addr_value,
        {"text": addr_value, "key": normalize_address(addr_value)},
        "address",
    )
    for doc, value in (
        (ins, "1,000 units LED Panel Light 600x600 mm, 40 W"),
        (bl, "LED Panel Light 600x600 mm, 40 W, 100 cartons"),
    ):
        c.add(doc, "goods", value, {"text": value, "key": normalize_product(value)}, "product")
    c.party(rc, "bank", "Pacific Harbour Bank")

    entities = _resolve(c)
    by_type: dict[str, list[str]] = {}
    for e in entities:
        by_type.setdefault(e.type, []).append(e.canonical_name)
    assert by_type["address"] == [addr_value]
    # Both goods descriptions are one product: quantity and carton count are ignored.
    assert len(by_type["product"]) == 1
    assert sorted(by_type["organization"]) == ["Global Trading Ltd", "Pacific Harbour Bank"]

    graph = project(CASE, c.docs, c.fields, entities, [])
    belongs = [e for e in graph.edges if e.type == "BELONGS_TO"]
    assert len(belongs) == 1
    assert sorted(map(str, belongs[0].evidence_ids)) == sorted(
        [str(address.field_id), str(supplier.field_id)]
    )
    product = next(e for e in entities if e.type == "product")
    goods_edges = [e for e in graph.edges if e.target_id == product.id]
    assert {e.source_id for e in goods_edges} == {ins, bl}
    assert all(e.type == "ASSOCIATED_WITH" for e in goods_edges)
    bank = next(e for e in entities if e.canonical_name == "Pacific Harbour Bank")
    assert any(
        e.source_id == rc and e.target_id == bank.id and e.properties["role"] == "bank"
        for e in graph.edges
    )
