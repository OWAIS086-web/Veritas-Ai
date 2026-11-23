"""Content of the synthetic shipment case (fictional companies, not a real transaction).

Each document is a list of blocks rendered by generate_samples.py into PDF, image, DOCX,
XLSX, CSV and EML. The ground truth used by tests is in GROUND_TRUTH. The application
never reads this module or the manifest.
"""

from __future__ import annotations

from typing import Any

LABEL = "SYNTHETIC DEMONSTRATION DATA"
FOOTER = "SYNTHETIC DEMONSTRATION DATA - fictional companies; not a real transaction."

SUPPLIER = "Global Trading Ltd"
SUPPLIER_ADDR = "Unit 7, 88 Harbour Road, Kowloon, Hong Kong"
BUYER = "ABC Imports Inc."
BUYER_ADDR = "1200 Commerce Way, Long Beach, CA 90802, USA"
PRODUCT = "LED Panel Light 600x600 mm, 40 W"
ITEMS_HEADER = ["Item", "Description", "HS Code", "Quantity", "Unit Price", "Amount"]
ITEMS = [["1", PRODUCT, "9405.42", "1,000", "USD 48.00", "USD 48,000.00"]]

Block = tuple[Any, ...]

DOCUMENTS: dict[str, dict[str, Any]] = {
    "01_purchase_order": {
        "title": "PURCHASE ORDER",
        "pages": [
            [
                ("kv", "Purchase Order No", "PO-2026-0815"),
                ("kv", "Order Date", "2 September 2026"),
                ("kv", "Supplier", SUPPLIER),
                ("kv", "Supplier Address", SUPPLIER_ADDR),
                ("kv", "Buyer", BUYER),
                ("kv", "Buyer Address", BUYER_ADDR),
                ("kv", "Shipment Reference", "SHIP-2049"),
                ("kv", "Currency", "USD"),
                ("table", ITEMS_HEADER, ITEMS),
                ("kv", "Total Quantity", "1,000 units"),
                ("kv", "Order Total", "USD 48,000.00"),
                ("note", "Delivery: FOB Hong Kong, shipment before 30 September 2026."),
            ]
        ],
    },
    "02_commercial_invoice": {
        "title": "COMMERCIAL INVOICE",
        "pages": [
            [
                ("kv", "Invoice No", "INV-2026-1042"),
                ("kv", "Invoice Date", "20 September 2026"),
                ("kv", "PO Reference", "PO-2026-0815"),
                ("kv", "Seller", SUPPLIER),
                ("kv", "Buyer", BUYER),
                ("kv", "Shipment Reference", "SHIP-2049"),
                ("kv", "Incoterms", "FOB Hong Kong"),
                ("table", ITEMS_HEADER, ITEMS),
                ("kv", "Total Quantity", "1,000 units"),
                ("kv", "Invoice Total", "USD 48,000.00"),
                ("note", "Payment terms: telegraphic transfer within 15 days of invoice date."),
            ]
        ],
    },
    "03_customs_declaration": {
        "title": "CUSTOMS DECLARATION",
        "pages": [
            [
                ("kv", "Declaration No", "CD-2026-55871"),
                ("kv", "Declaration Date", "14 October 2026"),
                ("kv", "Importer of Record", BUYER),
                ("kv", "Exporter", "GLOBAL TRADING LIMITED"),
                ("kv", "Invoice Reference", "INV-2026-1042"),
                ("kv", "Bill of Lading", "OCLU-BL-2026-77310"),
                ("kv", "Shipment Reference", "SHIP-2049"),
                ("kv", "Port of Entry", "Long Beach, USA"),
                (
                    "table",
                    ["Line", "Description", "HS Code", "Quantity", "Origin"],
                    [["1", PRODUCT, "9405.42", "1,000", "China"]],
                ),
                ("kv", "Total Quantity", "1,000 units"),
            ],
            [
                ("heading", "VALUATION"),
                ("kv", "Valuation Basis", "CIF Long Beach"),
                ("kv", "Currency", "USD"),
                ("kv", "Declared Customs Value", "USD 68,000.00"),
                (
                    "note",
                    "The declarant certifies that the particulars above are true and complete.",
                ),
            ],
        ],
    },
    "04_insurance_certificate": {
        "title": "CERTIFICATE OF MARINE INSURANCE",
        "pages": [
            [
                ("kv", "Certificate No", "MMI-CERT-2026-3301"),
                ("kv", "Date of Issue", "23 September 2026"),
                ("kv", "Insurer", "Meridian Marine Insurance Co."),
                ("kv", "Assured", BUYER),
                ("kv", "Shipper", SUPPLIER),
                ("kv", "Invoice Reference", "INV-2026-1042"),
                ("kv", "Shipment Reference", "SHIP-2049"),
                ("kv", "Vessel", "MV Northern Star, voyage 214E"),
                ("kv", "Voyage", "Hong Kong to Long Beach, USA"),
                ("kv", "Goods", f"1,000 units {PRODUCT}"),
                ("kv", "Insured Value", "USD 68,000.00"),
                ("note", "Conditions: Institute Cargo Clauses (A)."),
            ]
        ],
    },
    "05_payment_receipt": {
        "title": "PAYMENT RECEIPT",
        "pages": [
            [
                ("kv", "Receipt No", "RCPT-2026-0907"),
                ("kv", "Payment Date", "2 October 2026"),
                ("kv", "Payer", BUYER),
                ("kv", "Payee", SUPPLIER),
                ("kv", "Invoice Reference", "INV-2026-1042"),
                ("kv", "Bank", "Pacific Harbour Bank"),
                ("kv", "Bank Reference", "PHB-TT-20261002-4471"),
                ("kv", "Payment Method", "Telegraphic transfer"),
                ("kv", "Amount Paid", "USD 48,000.00"),
                ("note", "Received with thanks in full settlement of the invoice above."),
            ]
        ],
    },
    "06_packing_list": {
        "title": "PACKING LIST",
        "pages": [
            [
                ("kv", "Packing List No", "PL-2026-1042"),
                ("kv", "Packing Date", "21 September 2026"),
                ("kv", "Invoice Reference", "INV-2026-1042"),
                ("kv", "Shipper", SUPPLIER),
                ("kv", "Consignee", BUYER),
                ("kv", "Shipment Reference", "SHIP-2049"),
                (
                    "table",
                    ["Cartons", "Description", "Units per Carton", "Quantity", "Gross Weight"],
                    [["1-100", PRODUCT, "10", "1,000", "1,250 kg"]],
                ),
                ("kv", "Total Quantity", "1,000 units"),
                ("kv", "Total Cartons", "100"),
                ("kv", "Gross Weight", "1,250 kg"),
            ]
        ],
    },
    "07_bill_of_lading": {
        "title": "BILL OF LADING",
        "pages": [
            [
                ("kv", "Bill of Lading No", "OCLU-BL-2026-77310"),
                ("kv", "Shipped on Board Date", "24 September 2026"),
                ("kv", "Carrier", "Oceanic Line Shipping"),
                ("kv", "Shipper", SUPPLIER),
                ("kv", "Consignee", BUYER),
                ("kv", "Vessel", "MV Northern Star, voyage 214E"),
                ("kv", "Port of Loading", "Hong Kong"),
                ("kv", "Port of Discharge", "Long Beach, USA"),
                ("kv", "Shipment Reference", "SHIP-2049"),
                ("kv", "Description of Goods", f"{PRODUCT}, 100 cartons"),
                ("kv", "Total Quantity", "1,000 units"),
                ("note", "Shipped on board in apparent good order and condition."),
            ]
        ],
    },
}

# Ground truth for tests only (document_type, then expected normalized values).
GROUND_TRUTH: dict[str, dict[str, Any]] = {
    "01_purchase_order": {
        "doc_type": "purchase_order",
        "document_number": "PO-2026-0815",
        "total_amount": "48000.00",
        "total_page": 1,
        "total_quantity": 1000,
    },
    "02_commercial_invoice": {
        "doc_type": "commercial_invoice",
        "document_number": "INV-2026-1042",
        "total_amount": "48000.00",
        "total_page": 1,
        "total_quantity": 1000,
    },
    "03_customs_declaration": {
        "doc_type": "customs_declaration",
        "document_number": "CD-2026-55871",
        "total_amount": "68000.00",
        "total_page": 2,
        "total_quantity": 1000,
    },
    "04_insurance_certificate": {
        "doc_type": "insurance_certificate",
        "document_number": "MMI-CERT-2026-3301",
        "total_amount": "68000.00",
        "total_page": 1,
    },
    "05_payment_receipt": {
        "doc_type": "payment_receipt",
        "document_number": "RCPT-2026-0907",
        "total_amount": "48000.00",
        "total_page": 1,
    },
    "06_packing_list": {
        "doc_type": "packing_list",
        "document_number": "PL-2026-1042",
        "total_quantity": 1000,
    },
    "07_bill_of_lading": {
        "doc_type": "bill_of_lading",
        "document_number": "OCLU-BL-2026-77310",
        "total_quantity": 1000,
    },
}
