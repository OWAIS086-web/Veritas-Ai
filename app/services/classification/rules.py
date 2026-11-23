"""Rule-based document classification from titles and keywords.

The score is a rule-match ratio between the best and the runner-up type, not a probability.
Below the minimum title evidence the document is `unknown`; it is never guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

RULES_VERSION = "classify-rules-1.0"

DOC_TYPES: dict[str, dict[str, list[str]]] = {
    "purchase_order": {
        "titles": ["purchase order"],
        "keywords": ["po number", "order date", "order total", "supplier"],
    },
    "commercial_invoice": {
        "titles": ["commercial invoice", "tax invoice", "invoice"],
        "keywords": ["invoice no", "invoice date", "invoice total", "seller"],
    },
    "packing_list": {
        "titles": ["packing list"],
        "keywords": ["cartons", "gross weight", "packing date", "net weight"],
    },
    "bill_of_lading": {
        "titles": ["bill of lading", "sea waybill"],
        "keywords": [
            "port of loading",
            "port of discharge",
            "shipped on board",
            "vessel",
            "carrier",
        ],
    },
    "customs_declaration": {
        "titles": ["customs declaration", "import declaration", "entry summary"],
        "keywords": [
            "importer of record",
            "declared customs value",
            "hs code",
            "port of entry",
            "declaration no",
        ],
    },
    "certificate_of_origin": {
        "titles": ["certificate of origin"],
        "keywords": ["country of origin", "origin criterion"],
    },
    "insurance_certificate": {
        "titles": [
            "certificate of marine insurance",
            "insurance certificate",
            "certificate of insurance",
        ],
        "keywords": ["insured value", "assured", "insurer", "cargo clauses"],
    },
    "payment_receipt": {
        "titles": ["payment receipt", "payment advice", "remittance advice", "receipt"],
        "keywords": ["amount paid", "payment date", "payer", "payee", "bank reference"],
    },
    "supplier_agreement": {
        "titles": ["supply agreement", "supplier agreement"],
        "keywords": ["term of agreement", "governing law", "the parties"],
    },
    "inspection_certificate": {
        "titles": ["inspection certificate", "certificate of inspection"],
        "keywords": ["inspection date", "inspected by", "sampling"],
    },
}
TITLE_WEIGHT = 5
KEYWORD_WEIGHT = 1
TITLE_LINES = 3  # the title sits near the top; "Invoice Reference" further down isn't a title


@dataclass(frozen=True)
class Classification:
    doc_type: str
    score: float | None  # rule-match ratio in [0.5, 1], None for unknown
    method: str
    evidence: list[str]


def _contains(haystack: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", haystack) is not None


def classify(first_page_lines: list[str], full_text: str) -> Classification:
    head = "\n".join(first_page_lines[:TITLE_LINES]).casefold()
    body = full_text.casefold()
    scores: dict[str, tuple[int, list[str]]] = {}
    for doc_type, rule in DOC_TYPES.items():
        evidence: list[str] = []
        score = 0
        # Longest title first, so "commercial invoice" counts once, not also as "invoice".
        for title in sorted(rule["titles"], key=len, reverse=True):
            if _contains(head, title):
                score += TITLE_WEIGHT
                evidence.append(f"title:{title}")
                break
        for keyword in rule["keywords"]:
            if _contains(body, keyword):
                score += KEYWORD_WEIGHT
                evidence.append(f"keyword:{keyword}")
        scores[doc_type] = (score, evidence)
    ranked = sorted(scores.items(), key=lambda kv: kv[1][0], reverse=True)
    (best_type, (best, evidence)), (_, (second, _)) = ranked[0], ranked[1]
    if best < TITLE_WEIGHT or best == second:
        return Classification("unknown", None, RULES_VERSION, evidence if best else [])
    return Classification(best_type, round(best / (best + second), 3), RULES_VERSION, evidence)
