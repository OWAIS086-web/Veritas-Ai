# Design: Cross-Document Intelligence

## Components
- `app/services/comparison/persist.py` loads each completed document's latest extraction run for the case, runs the rules through `engine.py`, and upserts findings and evidence. A row lock on the case serializes concurrent comparisons.
- `app/services/comparison/engine.py` runs every registered rule. It is pure (no database access), and a rule that raises is isolated and reported as failed.
- `app/services/comparison/rules/*.py` holds one module per rule family: `financial.py`, `quantity.py`, `references.py`, `identity.py`, `duplicates.py`, `dates.py`, `missing.py`. Each exposes `RULES`, a tuple of `RuleSpec(rule_id, version, evaluate)`, where `evaluate(fields, docs, ctx) -> list[FindingDraft]` is a pure function, so it can be property-tested.
- `app/services/entity_resolution/names.py` reuses the extraction normalizer (casefold, strip legal suffixes, punctuation, whitespace) and computes similarity as the token-sort ratio from rapidfuzz (justification: a C-accelerated, well-tested fuzzy matcher; the stdlib `difflib` ratio isn't symmetric).
- `app/services/risk/scoring.py` computes:
  - `anomaly_score`: the magnitude, such as the relative difference capped at 1.0, the share of references outside the most common value, 1 minus the name similarity, or the date span over 30 days.
  - `evidence_confidence`: the minimum field confidence over the evidence, or null when any cited field has no measured confidence.
  - `priority`: a fixed matrix of severity and confidence. Confidence below 0.9 or unmeasured lowers it one level.
  - `severity_rationale`.
- `app/services/findings/service.py` handles listing, detail, status decisions (note required for `dismissed` and `confirmed_observation`, 409 without evidence), comments, and the overview counts.

## Data model (migration 0003)
- `findings`: `id, organization_id, case_id, finding_key (unique per case), rule_id, detected_by, type, title, severity, field, currency, difference, explanation, severity_rationale, limitations, anomaly_score, evidence_confidence, priority, evidence_status, status, requires_human_review, recommended_action, coverage, ai_output_json, active, last_detected_at, created_at, updated_at`.
  - `ai_output_json` is the detector's original output. In this phase that is always the deterministic rule output, with `detector = "rules"` and `model = null`.
  - `active` is false when the latest run no longer detects the finding.
- `evidence_items(id, organization_id, finding_id, document_id, extracted_field_id null, field_name, page_number, bbox, location, value, normalized_value, confidence, role supporting|conflicting|context, created_at)`. The field id is set to null if the field's extraction run is replaced, and the snapshot columns keep the cited value.
- `finding_decisions(id, organization_id, finding_id, actor_user_id, from_status, to_status, note, created_at)`. Append-only (SELECT and INSERT grants only).
- `investigator_comments(id, organization_id, finding_id, user_id, body, created_at)`. Append-only.
- `cases.compared_at` records the last comparison. `finding_count` is null until a case has been compared.
- Triggers:
  - `enforce_finding_evidence()` raises when a finding is set to `confirmed_observation` without evidence items.
  - `protect_finding_ai_output()` blocks any change to `ai_output_json`.
  - `enforce_evidence_scope()` rejects evidence whose document is outside the finding's case, or whose field belongs to another document. The trigger functions run as the invoking role, so RLS hides other organizations' rows from their checks.

## API
- `POST /cases/{id}/compare` (job, `findings:run`)
- `GET /cases/{id}/findings`
- `GET /findings` (filters and cursor pagination)
- `GET /findings/{id}`
- `GET /findings/{id}/evidence` (`findings:read`)
- `PATCH /findings/{id}/status` (`findings:review`, 409 without evidence)
- `POST /findings/{id}/comments` (`findings:comment`)

## Data flow
A processing batch finishes → the comparison runs in the same job for every case the batch touched (events `comparison_started` and `comparison_completed`) → findings and evidence are upserted. A manual run goes through `POST /cases/{id}/compare` and the `cases.compare` Celery task. The outbox to the graph arrives with the evidence-knowledge-graph spec.

## Failure handling
- A document with a missing or uncertain field is skipped for that rule, and the skip is recorded in the finding's `coverage.skipped`, with the reason.
- The missing-document rule doesn't run while any document of the case is still uploaded or processing.
- Rule exceptions are isolated per rule. The job result lists `rules_failed`, and findings of a failed rule are left unchanged.
- A comparison failure at the end of a processing batch is reported as `comparison_failed`. It doesn't fail the processed documents.

## Testing
- Property: amount comparison is symmetric and order-independent, and different currencies never produce a financial finding. Dates with different roles never conflict. A finding cites every value of its currency.
- Integration:
  - The demo case yields exactly one 20,000 USD finding with 5 evidence items, and no quantity finding.
  - A re-run keeps the status, evidence ids and `ai_output_json`.
  - The triggers and append-only grants hold.
  - Cross-org access gives 404.
