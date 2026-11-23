"""Field catalogue per document type: what to extract, how to find it, how to type it."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSpec:
    name: str
    value_type: str  # reference | party | amount | quantity | date | text | currency
    #                  | address | product
    labels: tuple[str, ...]
    role: str | None = None  # semantic role (dates and amounts)
    required: bool = True


def _f(
    name: str, value_type: str, *labels: str, role: str | None = None, required: bool = True
) -> FieldSpec:
    return FieldSpec(name, value_type, labels, role, required)


SHIPMENT = _f(
    "shipment_reference", "reference", "Shipment Reference", "Shipment Ref", "Shipment No"
)
INVOICE_REF = _f(
    "invoice_reference", "reference", "Invoice Reference", "Invoice Ref", "Commercial Invoice No"
)
QUANTITY = _f("total_quantity", "quantity", "Total Quantity", "Total Qty", "Quantity")
CURRENCY = _f("currency", "currency", "Currency", required=False)

FIELDS: dict[str, tuple[FieldSpec, ...]] = {
    "purchase_order": (
        _f("document_number", "reference", "Purchase Order No", "PO Number", "PO No"),
        _f("document_date", "date", "Order Date", "PO Date", role="order_date"),
        _f("supplier", "party", "Supplier", "Vendor", "Seller"),
        _f("buyer", "party", "Buyer", "Purchaser"),
        _f("supplier_address", "address", "Supplier Address", "Vendor Address", required=False),
        _f("buyer_address", "address", "Buyer Address", "Delivery Address", required=False),
        SHIPMENT,
        CURRENCY,
        QUANTITY,
        _f(
            "total_amount",
            "amount",
            "Order Total",
            "PO Total",
            "Total Amount",
            "Grand Total",
            role="order_total",
        ),
    ),
    "commercial_invoice": (
        _f("document_number", "reference", "Invoice No", "Invoice Number"),
        _f("document_date", "date", "Invoice Date", role="invoice_date"),
        _f("po_reference", "reference", "PO Reference", "Purchase Order No", "PO No"),
        _f("supplier", "party", "Seller", "Supplier", "Exporter"),
        _f("buyer", "party", "Buyer", "Consignee", "Bill To"),
        SHIPMENT,
        _f("incoterms", "text", "Incoterms", "Delivery Terms", required=False),
        CURRENCY,
        QUANTITY,
        _f(
            "total_amount",
            "amount",
            "Invoice Total",
            "Total Amount",
            "Grand Total",
            "Amount Due",
            role="invoice_total",
        ),
    ),
    "customs_declaration": (
        _f("document_number", "reference", "Declaration No", "Entry No", "Declaration Number"),
        _f("document_date", "date", "Declaration Date", "Entry Date", role="declaration_date"),
        _f("buyer", "party", "Importer of Record", "Importer", "Consignee"),
        _f("supplier", "party", "Exporter", "Consignor", "Seller"),
        INVOICE_REF,
        _f("bill_of_lading_reference", "reference", "Bill of Lading", "B/L No", required=False),
        SHIPMENT,
        _f("valuation_basis", "text", "Valuation Basis", required=False),
        CURRENCY,
        QUANTITY,
        _f(
            "total_amount",
            "amount",
            "Declared Customs Value",
            "Customs Value",
            "Declared Value",
            role="declared_customs_value",
        ),
    ),
    "insurance_certificate": (
        _f("document_number", "reference", "Certificate No", "Policy No"),
        _f("document_date", "date", "Date of Issue", "Issue Date", role="issue_date"),
        _f("buyer", "party", "Assured", "Insured"),
        _f("supplier", "party", "Shipper", required=False),
        _f("insurer", "party", "Insurer", "Underwriter", required=False),
        INVOICE_REF,
        SHIPMENT,
        _f("vessel", "text", "Vessel", required=False),
        _f("goods", "product", "Goods", "Subject-matter Insured", required=False),
        CURRENCY,
        _f(
            "total_amount",
            "amount",
            "Insured Value",
            "Sum Insured",
            "Amount Insured",
            role="insured_value",
        ),
    ),
    "payment_receipt": (
        _f("document_number", "reference", "Receipt No", "Receipt Number", "Payment Reference"),
        _f("document_date", "date", "Payment Date", "Value Date", role="payment_date"),
        _f("buyer", "party", "Payer", "Remitter"),
        _f("supplier", "party", "Payee", "Beneficiary"),
        INVOICE_REF,
        _f("bank", "party", "Bank", "Paying Bank", "Remitting Bank", required=False),
        _f(
            "bank_reference", "reference", "Bank Reference", "Transaction Reference", required=False
        ),
        CURRENCY,
        _f(
            "total_amount",
            "amount",
            "Amount Paid",
            "Amount Received",
            "Payment Amount",
            role="amount_paid",
        ),
    ),
    "packing_list": (
        _f("document_number", "reference", "Packing List No", "Packing List Number"),
        _f("document_date", "date", "Packing Date", role="packing_date"),
        INVOICE_REF,
        _f("supplier", "party", "Shipper", "Exporter", "Seller"),
        _f("buyer", "party", "Consignee", "Buyer"),
        SHIPMENT,
        QUANTITY,
        _f("total_cartons", "quantity", "Total Cartons", "Total Packages", required=False),
        _f("gross_weight", "quantity", "Gross Weight", required=False),
    ),
    "bill_of_lading": (
        _f("document_number", "reference", "Bill of Lading No", "B/L No", "BL No"),
        _f(
            "document_date",
            "date",
            "Shipped on Board Date",
            "On Board Date",
            "Date of Shipment",
            role="shipment_date",
        ),
        _f("supplier", "party", "Shipper"),
        _f("buyer", "party", "Consignee"),
        _f("vessel", "text", "Vessel", required=False),
        _f("port_of_loading", "text", "Port of Loading", required=False),
        _f("port_of_discharge", "text", "Port of Discharge", required=False),
        _f("goods", "product", "Description of Goods", "Goods", required=False),
        SHIPMENT,
        QUANTITY,
    ),
}


def fields_for(doc_type: str) -> tuple[FieldSpec, ...]:
    return FIELDS.get(doc_type, ())
