"""Builders for comparison-rule tests: fields shaped exactly like persisted extracted_fields.

The demo case mirrors the synthetic shipment (SYNTHETIC DEMONSTRATION DATA) value for value,
so unit tests and the integration test assert the same outcome.
"""

from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal
from typing import Any

from app.services.comparison.model import DocInfo, FieldObs, RuleContext
from app.services.extraction.normalize import normalize_name, normalize_reference

CTX = RuleContext(
    investigation_type="international_shipment",
    amount_tolerance=Decimal("0.005"),
    name_threshold=0.85,
)


class Case:
    def __init__(self) -> None:
        self.docs: list[DocInfo] = []
        self.fields: list[FieldObs] = []

    def doc(self, doc_type: str | None, filename: str, status: str = "completed") -> uuid.UUID:
        doc_id = uuid.uuid4()
        sha = hashlib.sha256(doc_id.bytes).hexdigest()
        self.docs.append(DocInfo(doc_id, filename, doc_type, sha, status))
        return doc_id

    def add(
        self,
        doc_id: uuid.UUID,
        name: str,
        value: str | None,
        normalized: Any,
        value_type: str,
        *,
        role: str | None = None,
        currency: str | None = None,
        page: int | None = 1,
        status: str = "extracted",
        confidence: Decimal | None = Decimal("1.000"),
        reason: str | None = None,
    ) -> FieldObs:
        doc = next(d for d in self.docs if d.id == doc_id)
        obs = FieldObs(
            field_id=uuid.uuid4(),
            document_id=doc_id,
            doc_type=doc.doc_type,
            filename=doc.filename,
            name=name,
            value=value,
            normalized=normalized,
            value_type=value_type,
            currency=currency,
            role=role,
            confidence=confidence,
            page_number=page,
            bbox=[10.0, 20.0, 200.0, 32.0] if page else None,
            location=None if page else "Sheet1!B7",
            status=status,
            rejection_reason=reason,
        )
        self.fields.append(obs)
        return obs

    def amount(
        self, doc_id: uuid.UUID, amount: str, currency: str | None = "USD", **kw: Any
    ) -> FieldObs:
        return self.add(
            doc_id,
            "total_amount",
            f"{currency or ''} {amount}".strip(),
            {"amount": f"{Decimal(amount):.2f}", "currency": currency},
            "amount",
            currency=currency,
            **kw,
        )

    def quantity(self, doc_id: uuid.UUID, qty: int, unit: str = "units", **kw: Any) -> FieldObs:
        return self.add(
            doc_id,
            "total_quantity",
            f"{qty:,} {unit}",
            {"quantity": str(qty), "unit": unit},
            "quantity",
            **kw,
        )

    def ref(self, doc_id: uuid.UUID, name: str, value: str, **kw: Any) -> FieldObs:
        return self.add(
            doc_id,
            name,
            value,
            {"reference": value, "key": normalize_reference(value)},
            "reference",
            **kw,
        )

    def party(self, doc_id: uuid.UUID, name: str, value: str, **kw: Any) -> FieldObs:
        return self.add(
            doc_id, name, value, {"name": value, "key": normalize_name(value)}, "party", **kw
        )

    def date(self, doc_id: uuid.UUID, role: str, iso: str, **kw: Any) -> FieldObs:
        return self.add(
            doc_id, "document_date", iso, {"date": iso, "role": role}, "date", role=role, **kw
        )


SUPPLIER, BUYER = "Global Trading Ltd", "ABC Imports Inc."


def demo_case() -> Case:
    c = Case()
    po = c.doc("purchase_order", "01_purchase_order.pdf")
    inv = c.doc("commercial_invoice", "02_commercial_invoice.pdf")
    cd = c.doc("customs_declaration", "03_customs_declaration.pdf")
    ins = c.doc("insurance_certificate", "04_insurance_certificate.pdf")
    rc = c.doc("payment_receipt", "05_payment_receipt.pdf")
    pl = c.doc("packing_list", "06_packing_list.pdf")
    bl = c.doc("bill_of_lading", "07_bill_of_lading.pdf")

    c.ref(po, "document_number", "PO-2026-0815")
    c.date(po, "order_date", "2026-09-02")
    c.party(po, "supplier", SUPPLIER)
    c.party(po, "buyer", BUYER)
    c.ref(po, "shipment_reference", "SHIP-2049")
    c.quantity(po, 1000)
    c.amount(po, "48000", role="order_total")

    c.ref(inv, "document_number", "INV-2026-1042")
    c.date(inv, "invoice_date", "2026-09-20")
    c.ref(inv, "po_reference", "PO-2026-0815")
    c.party(inv, "supplier", SUPPLIER)
    c.party(inv, "buyer", BUYER)
    c.ref(inv, "shipment_reference", "SHIP-2049")
    c.add(inv, "incoterms", "FOB Hong Kong", {"text": "FOB Hong Kong"}, "text")
    c.quantity(inv, 1000)
    c.amount(inv, "48000", role="invoice_total")

    c.ref(cd, "document_number", "CD-2026-55871")
    c.date(cd, "declaration_date", "2026-10-14")
    c.party(cd, "buyer", BUYER)
    c.party(cd, "supplier", "GLOBAL TRADING LIMITED")
    c.ref(cd, "invoice_reference", "INV-2026-1042")
    c.ref(cd, "bill_of_lading_reference", "OCLU-BL-2026-77310")
    c.ref(cd, "shipment_reference", "SHIP-2049")
    c.add(cd, "valuation_basis", "CIF Long Beach", {"text": "CIF Long Beach"}, "text", page=2)
    c.quantity(cd, 1000)
    c.amount(cd, "68000", role="declared_customs_value", page=2)

    c.ref(ins, "document_number", "MMI-CERT-2026-3301")
    c.date(ins, "issue_date", "2026-09-23")
    c.party(ins, "buyer", BUYER)
    c.party(ins, "supplier", SUPPLIER)
    c.ref(ins, "invoice_reference", "INV-2026-1042")
    c.ref(ins, "shipment_reference", "SHIP-2049")
    c.amount(ins, "68000", role="insured_value")

    c.ref(rc, "document_number", "RCPT-2026-0907")
    c.date(rc, "payment_date", "2026-10-02")
    c.party(rc, "buyer", BUYER)
    c.party(rc, "supplier", SUPPLIER)
    c.ref(rc, "invoice_reference", "INV-2026-1042")
    c.amount(rc, "48000", role="amount_paid")

    c.ref(pl, "document_number", "PL-2026-1042")
    c.date(pl, "packing_date", "2026-09-21")
    c.ref(pl, "invoice_reference", "INV-2026-1042")
    c.party(pl, "supplier", SUPPLIER)
    c.party(pl, "buyer", BUYER)
    c.ref(pl, "shipment_reference", "SHIP-2049")
    c.quantity(pl, 1000)

    c.ref(bl, "document_number", "OCLU-BL-2026-77310")
    c.date(bl, "shipment_date", "2026-09-24")
    c.party(bl, "supplier", SUPPLIER)
    c.party(bl, "buyer", BUYER)
    c.ref(bl, "shipment_reference", "SHIP-2049")
    c.quantity(bl, 1000)
    return c
