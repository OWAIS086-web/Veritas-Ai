# Requirements: Cross-Document Intelligence

## Introduction
The core engine. It compares extracted fields across all documents in a case, detects contradictions and missing evidence, and persists findings linked to their source evidence.

## Requirement 1: Comparable field groups
1. THE SYSTEM SHALL group fields for comparison by `(semantic field, currency for money, semantic role for dates)` across the documents of one case.
2. THE SYSTEM SHALL NOT compare monetary amounts with different currencies. It SHALL emit a `currency_mismatch` observation (informational) instead.
3. THE SYSTEM SHALL NOT compare dates with different semantic roles (for example `invoice_date` and `shipment_date`).

## Requirement 2: Financial reconciliation
1. WHEN documents in the same shipment declare `total_amount` values that differ by more than `VERITAS_AMOUNT_TOLERANCE` (default 0.005 relative) in the same currency THE SYSTEM SHALL create one `financial_discrepancy` finding listing every observation `{document_id, field_id, page, bbox, value}` and `difference = max - min`.
2. GIVEN the demo case (PO, invoice and receipt at 48,000 USD; customs and insurance at 68,000 USD) THE SYSTEM SHALL produce exactly one financial discrepancy with `difference = 20000.00 USD` and 5 evidence items.

## Requirement 3: Other comparisons
1. Quantity mismatch: unit totals on the packing list, bill of lading and invoice. GIVEN 1,000 = 1,000 THE SYSTEM SHALL create no quantity finding.
2. Conflicting reference: shipment, PO or invoice references that should match but don't.
3. Identity mismatch: supplier or buyer names whose fuzzy similarity is below the threshold after normalization (suffixes such as Ltd/Limited and punctuation removed).
4. Duplicate document: the same sha256, or the same document number with different content.
5. Date inconsistency: same-role dates that differ, or business-rule ordering (for example a payment date before the invoice date is flagged as informational).

## Requirement 4: Missing documents
1. WHEN the case type is `international_shipment` and an expected document type (PO, invoice, packing list, bill of lading, customs declaration, payment receipt) is absent THE SYSTEM SHALL create a `missing_document` finding with no evidence items, `evidence_status = absence`, and an explanation listing what was expected.

## Requirement 5: Findings
1. Each finding SHALL store `type, severity, field, currency, difference, explanation, severity_rationale, anomaly_score, evidence_confidence, priority, status=new, requires_human_review, recommended_action, ai_output_json` (immutable) and `detected_by` (the rule id and version).
2. Re-running the comparison SHALL be idempotent: findings are keyed by `(case_id, rule_id, field_signature)`. Existing findings keep their human status, and only the evidence is refreshed.
3. Evidence items SHALL reference `extracted_fields` rows of the same organization and case.

## Requirement 6: LLM-assisted interpretation
1. WHEN deterministic rules cannot decide (for example product descriptions) THE SYSTEM MAY ask the provider for a semantic-equivalence judgment. The result SHALL be stored as an *interpretation* with model metadata and SHALL NOT create a finding above `medium` severity on its own.
