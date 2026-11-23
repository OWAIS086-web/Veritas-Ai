"""Comparison rules: positive and negative cases per rule, plus the demo case outcome."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.services.comparison.engine import evaluate_all
from app.services.comparison.model import RuleSpec, coverage_for
from app.services.comparison.rules import (
    dates,
    duplicates,
    financial,
    identity,
    missing,
    quantity,
    references,
)
from tests.unit.comparison_fixtures import CTX, Case, demo_case


def test_demo_case_yields_exactly_one_financial_discrepancy() -> None:
    c = demo_case()
    result = evaluate_all(c.fields, c.docs, CTX)
    assert result.failed == {}
    assert [d.type for d in result.drafts] == ["financial_discrepancy"]
    [finding] = result.drafts
    assert finding.difference == Decimal("20000")
    assert finding.currency == "USD" and finding.field == "total_amount"
    assert finding.severity == "high"
    assert finding.anomaly_score == Decimal("0.294")
    assert len(finding.evidence) == 5
    cited = {e.obs.doc_type for e in finding.evidence}
    assert cited == {
        "purchase_order",
        "commercial_invoice",
        "payment_receipt",
        "customs_declaration",
        "insurance_certificate",
    }
    assert "USD 20,000.00" in finding.title
    # Context that can explain part of the difference is stated as a limitation.
    assert any("FOB" in note and "CIF" in note for note in finding.limitations)
    assert finding.coverage["skipped"] == []


def test_demo_explanation_never_concludes_wrongdoing() -> None:
    c = demo_case()
    [finding] = evaluate_all(c.fields, c.docs, CTX).drafts
    text = " ".join([finding.title, finding.explanation, *finding.limitations]).lower()
    for word in ("fraud", "forged", "fake", "authentic", "guilty"):
        assert word not in text


# --- financial ---------------------------------------------------------------------------


def test_amounts_within_tolerance_are_not_reported() -> None:
    c = Case()
    a, b = c.doc("commercial_invoice", "a.pdf"), c.doc("payment_receipt", "b.pdf")
    c.amount(a, "48000.00")
    c.amount(b, "48200.00")  # 0.41% < 0.5%
    assert financial.evaluate_amounts(c.fields, c.docs, CTX) == []


def test_different_currencies_are_not_compared_but_observed() -> None:
    c = Case()
    a, b = c.doc("commercial_invoice", "a.pdf"), c.doc("customs_declaration", "b.pdf")
    c.amount(a, "48000", "USD")
    c.amount(b, "44000", "EUR")
    assert financial.evaluate_amounts(c.fields, c.docs, CTX) == []
    [observation] = financial.evaluate_currencies(c.fields, c.docs, CTX)
    assert observation.type == "currency_mismatch" and observation.severity == "info"
    assert {e.role for e in observation.evidence} == {"context"}


def test_uncertain_amounts_are_skipped_and_reported_in_coverage() -> None:
    c = Case()
    a, b, x = (
        c.doc("commercial_invoice", "a.pdf"),
        c.doc("customs_declaration", "b.pdf"),
        c.doc("payment_receipt", "x.pdf"),
    )
    c.amount(a, "48000")
    c.amount(b, "68000")
    c.add(x, "total_amount", None, None, "amount", status="uncertain", reason="not_found")
    [finding] = financial.evaluate_amounts(c.fields, c.docs, CTX)
    assert len(finding.evidence) == 2
    assert finding.coverage["skipped"] == [
        {"document_id": str(x), "filename": "x.pdf", "reason": "not_found"}
    ]


def test_a_single_document_is_never_a_discrepancy() -> None:
    c = Case()
    a = c.doc("commercial_invoice", "a.pdf")
    c.amount(a, "48000")
    assert financial.evaluate_amounts(c.fields, c.docs, CTX) == []


# --- quantity ----------------------------------------------------------------------------


def test_quantity_mismatch_and_equal_quantities() -> None:
    c = Case()
    pl, bl = c.doc("packing_list", "pl.pdf"), c.doc("bill_of_lading", "bl.pdf")
    c.quantity(pl, 1000)
    c.quantity(bl, 1000)
    assert quantity.evaluate(c.fields, c.docs, CTX) == []
    c.fields[-1] = replace(c.fields[-1], normalized={"quantity": "900", "unit": "units"})
    [finding] = quantity.evaluate(c.fields, c.docs, CTX)
    assert finding.type == "quantity_mismatch" and finding.severity == "high"
    assert finding.anomaly_score == Decimal("0.100")


def test_quantities_in_different_units_are_not_compared() -> None:
    c = Case()
    pl, bl = c.doc("packing_list", "pl.pdf"), c.doc("bill_of_lading", "bl.pdf")
    c.quantity(pl, 1000, "units")
    c.quantity(bl, 100, "cartons")
    assert quantity.evaluate(c.fields, c.docs, CTX) == []


# --- references --------------------------------------------------------------------------


def test_conflicting_invoice_reference() -> None:
    c = Case()
    inv, cd = c.doc("commercial_invoice", "inv.pdf"), c.doc("customs_declaration", "cd.pdf")
    c.ref(inv, "document_number", "INV-2026-1042")
    c.ref(cd, "invoice_reference", "INV 2026/1042")  # same after normalization
    assert references.evaluate(c.fields, c.docs, CTX) == []
    c.ref(c.doc("payment_receipt", "rc.pdf"), "invoice_reference", "INV-2026-9999")
    [finding] = references.evaluate(c.fields, c.docs, CTX)
    assert finding.type == "conflicting_reference" and finding.field == "invoice_reference"
    assert finding.anomaly_score == Decimal("0.333")
    assert len(finding.evidence) == 3


def test_numbers_of_other_document_types_are_not_references() -> None:
    c = Case()
    c.ref(c.doc("packing_list", "pl.pdf"), "document_number", "PL-1")
    c.ref(c.doc("payment_receipt", "rc.pdf"), "document_number", "RC-1")
    assert references.evaluate(c.fields, c.docs, CTX) == []


# --- identity ----------------------------------------------------------------------------


def test_identity_mismatch_and_suffix_variants() -> None:
    c = Case()
    a, b = c.doc("commercial_invoice", "a.pdf"), c.doc("customs_declaration", "b.pdf")
    c.party(a, "supplier", "Global Trading Ltd")
    c.party(b, "supplier", "GLOBAL TRADING LIMITED")
    assert identity.evaluate(c.fields, c.docs, CTX) == []
    c.party(c.doc("bill_of_lading", "bl.pdf"), "supplier", "Northwind Freight Partners")
    [finding] = identity.evaluate(c.fields, c.docs, CTX)
    assert finding.type == "identity_mismatch" and finding.field == "supplier"
    assert finding.anomaly_score is not None and finding.anomaly_score > Decimal("0.15")


# --- duplicates --------------------------------------------------------------------------


def test_same_number_with_different_content_is_a_duplicate() -> None:
    c = Case()
    a, b = c.doc("commercial_invoice", "a.pdf"), c.doc("commercial_invoice", "a-v2.pdf")
    c.ref(a, "document_number", "INV-2026-1042")
    c.ref(b, "document_number", "INV-2026-1042")
    [finding] = duplicates.evaluate(c.fields, c.docs, CTX)
    assert finding.type == "duplicate_document" and len(finding.evidence) == 2


def test_identical_bytes_are_a_duplicate_and_distinct_numbers_are_not() -> None:
    c = Case()
    a, b = c.doc("commercial_invoice", "a.pdf"), c.doc("commercial_invoice", "b.pdf")
    c.ref(a, "document_number", "INV-1")
    c.ref(b, "document_number", "INV-2")
    assert duplicates.evaluate(c.fields, c.docs, CTX) == []
    c.docs[1] = replace(c.docs[1], sha256=c.docs[0].sha256)
    [finding] = duplicates.evaluate(c.fields, c.docs, CTX)
    assert finding.signature.startswith("sha256:") and finding.severity == "low"


# --- dates -------------------------------------------------------------------------------


def test_same_role_dates_that_differ() -> None:
    c = Case()
    c.date(c.doc("bill_of_lading", "bl.pdf"), "shipment_date", "2026-09-24")
    c.date(c.doc("bill_of_lading", "bl2.pdf"), "shipment_date", "2026-09-24")
    assert dates.evaluate_same_role(c.fields, c.docs, CTX) == []
    c.date(c.doc("bill_of_lading", "bl3.pdf"), "shipment_date", "2026-10-09")
    [finding] = dates.evaluate_same_role(c.fields, c.docs, CTX)
    assert finding.details["span_days"] == 15 and finding.anomaly_score == Decimal("0.500")


def test_payment_before_invoice_is_informational() -> None:
    c = Case()
    inv = c.doc("commercial_invoice", "inv.pdf")
    rc = c.doc("payment_receipt", "rc.pdf")
    c.date(inv, "invoice_date", "2026-09-20")
    c.date(rc, "payment_date", "2026-10-02")
    assert dates.evaluate_order(c.fields, c.docs, CTX) == []
    c.fields[-1] = replace(c.fields[-1], normalized={"date": "2026-09-01", "role": "payment_date"})
    [finding] = dates.evaluate_order(c.fields, c.docs, CTX)
    assert finding.severity == "info" and finding.signature == "payment_before_invoice"


# --- missing -----------------------------------------------------------------------------


def test_missing_documents_for_a_shipment_case() -> None:
    c = demo_case()
    c.docs = [d for d in c.docs if d.doc_type != "packing_list"]
    [finding] = missing.evaluate(c.fields, c.docs, CTX)
    assert finding.type == "missing_document" and finding.evidence == []
    assert finding.evidence_status == "absence"
    assert "packing list" in finding.explanation and "bill of lading" in finding.explanation


def test_missing_is_not_decided_while_documents_are_pending_or_for_other_types() -> None:
    c = Case()
    c.doc("commercial_invoice", "inv.pdf")
    assert missing.evaluate(c.fields, c.docs, replace(CTX, pending_documents=1)) == []
    assert missing.evaluate(c.fields, c.docs, replace(CTX, investigation_type="other")) == []
    assert missing.evaluate([], [], CTX) == []


def test_failed_documents_are_named_as_a_limitation() -> None:
    c = Case()
    c.doc("commercial_invoice", "inv.pdf")
    c.doc(None, "broken.pdf", status="failed")
    drafts = missing.evaluate(c.fields, c.docs, CTX)
    assert len(drafts) == 5
    assert all("broken.pdf" in d.limitations[0] for d in drafts)


# --- engine ------------------------------------------------------------------------------


def test_a_failing_rule_is_isolated() -> None:
    def broken(*_: object) -> list[object]:
        raise RuntimeError("boom")

    c = demo_case()
    rules = (RuleSpec("broken", "1", broken), *financial.RULES)  # type: ignore[arg-type]
    result = evaluate_all(c.fields, c.docs, CTX, rules)
    assert result.failed == {"broken": "RuntimeError"}
    assert [d.type for d in result.drafts] == ["financial_discrepancy"]


def test_coverage_lists_expected_documents_without_the_field() -> None:
    c = Case()
    inv = c.doc("commercial_invoice", "inv.pdf")
    rc = c.doc("payment_receipt", "rc.pdf")
    c.amount(inv, "100")
    cov = coverage_for("total_amount", c.fields, c.docs)
    assert cov["compared_documents"] == [str(inv)]
    assert cov["skipped"] == [{"document_id": str(rc), "filename": "rc.pdf", "reason": "absent"}]
