---
inclusion: auto
name: data-governance
description: Evidence provenance, citation integrity, data retention, soft deletion and audit logging rules. Use when working on findings, evidence items, reports, audit logs, retention or anything that cites document evidence.
---

# Data governance: provenance, retention and audit

## Evidence chain (must never break)
original file (`documents.sha256`, immutable storage key) → `document_pages` → `extracted_fields` (page, bbox, method, model_version) → `evidence_items` → `findings` → report citations (and graph edges carrying `evidence_id`).

- A finding cannot reach `confirmed_observation` unless it has at least one `evidence_items` row. This is enforced in the service and by a database trigger.
- Every evidence item references an existing document in the **same organization and case**.
- Reports are generated only from persisted findings and evidence. A citation verifier re-resolves every `(finding_id, document_id, page)` before export and fails the export on any orphan.
- `findings.ai_output_json` is written once and never updated. Human decisions go to `finding_decisions` (append-only) with actor, from/to status, note and timestamp.

## Retention and deletion
- Cases are soft-deleted (`deleted_at`). Soft-deleted data is hidden from every API.
- `organizations.retention_days` (nullable means keep forever) drives a scheduled purge job (later phase). The purge deletes storage objects and rows, and writes an audit entry with counts only.
- Originals are never overwritten. A new upload with different bytes becomes a new `document_versions` row.

## Audit
- `audit_logs` is append-only. The application role has INSERT and SELECT only, with no UPDATE or DELETE.
- Each entry records `organization_id, actor_user_id, action, resource_type, resource_id, ip, user_agent, created_at, metadata` (metadata never holds secrets or document text).
