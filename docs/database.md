# Database

PostgreSQL 16 is the source of truth. The schema is managed only by Alembic (`backend/migrations`), run as the owner role by the one-shot `migrate` service.

## Roles
| Role | Created by | Privileges |
|---|---|---|
| owner (`POSTGRES_USER`) | Postgres image | Owns all tables. Used only by migrations. |
| `veritas_app` | `infrastructure/docker/postgres/init/01-roles.sh` | Not owner, `NOBYPASSRLS`. Least-privilege grants per table. Used by the API and workers. |
| `veritas_readonly` | same | SELECT only, subject to RLS. Used by the read-only Kiro Postgres MCP server. |

## Row-level security
Every tenant-owned table has RLS enabled with the policy
`organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid` (or `id = …` on `organizations`). Each request transaction sets the tenant with `set_config('app.current_org', :org, true)`. Without a tenant set, tenant tables return no rows.

Two owner-owned `SECURITY DEFINER` functions handle the only cross-tenant reads, which are needed before authentication. Only `veritas_app` may execute them:
- `auth_memberships(user_id)` returns `(organization_id, organization_name, organization_slug, role_key, joined_at)`.
- `auth_find_refresh(token_hash)` returns the refresh token row.

RLS is deliberately not `FORCE`d, so these owner-owned functions can work. The application role never owns a table, so the policies always apply to it. `tests/integration/test_rls.py` checks this.

## Tables (migration 0001)
| Table | Tenant | Notes |
|---|---|---|
| organizations | by `id` | `slug` unique, `retention_days` nullable |
| users | global | `email` unique (stored lowercase). Argon2id `password_hash`. |
| roles | global | Seeded: org_admin, investigation_manager, investigator, reviewer, read_only_analyst |
| organization_members | ● | unique `(organization_id, user_id)` |
| refresh_tokens | ● | `token_hash` unique, `family_id` indexed, rotation chain via `replaced_by_id` |
| audit_logs | ● (nullable for unattributed events) | Append-only: `veritas_app` has INSERT and SELECT only. Inserts don't use `RETURNING`, because the SELECT policy would reject unattributed rows. |
| jobs | ● | Status, attempts, `max_attempts`, error, payload, result |
| job_events | ● | Unique `(job_id, seq)`. The SSE stream reads these. |

## Tables (migration 0002)
All seven tables are tenant-owned (`organization_id NOT NULL`, indexed, RLS enabled with the policy above). The `veritas_app` grants are listed per table. `cases`, `documents` and `document_versions` have no `DELETE` grant.

| Table | `veritas_app` grants | Notes |
|---|---|---|
| cases | SELECT, INSERT, UPDATE | Investigations. Soft delete through `deleted_at`. Index `(organization_id, created_at)` for cursor pagination. |
| documents | SELECT, INSERT, UPDATE | One row per uploaded original. Unique `(organization_id, case_id, sha256)` gives duplicate detection. `storage_key` is server-generated and prefixed with the organization id. Holds `mime_type` and `detection_reason` (from magic bytes), `doc_type`, `classification_confidence`, `language`, `status`, `current_stage` and `pipeline_version`. |
| document_versions | SELECT, INSERT | Links a document to the one it supersedes, with its `sha256`. Insert-only. |
| document_stages | SELECT, INSERT, UPDATE | Per-stage status, attempts, timings, error and `metrics`. Unique `(document_id, stage, pipeline_version)` makes reprocessing idempotent. |
| document_pages | SELECT, INSERT, UPDATE, DELETE | Page text, `lines` (tokens with bounding boxes) and `tables` as JSONB, page `width`/`height`, `coord_unit`, `method` (text layer or OCR) and `ocr_mean_confidence` (null unless OCR produced it). Rows are replaced when a document is reprocessed. |
| extraction_runs | SELECT, INSERT, UPDATE, DELETE | One per extraction attempt: `method` (`rules` or `llm`), `provider`, `model_version`, `prompt_version`, `status` and `notes`. |
| extracted_fields | SELECT, INSERT, DELETE | One row per field: `value`, `normalized_value`, `value_type`, `currency`, `semantic_role`, `confidence`, `page_number`, `bbox`, `location` (for cell or line references), `method`, `model_version`, `status` and `rejection_reason`. A value that can't be verified on its cited page is stored as `null` with status `uncertain`. Rows are never updated. |

## Tables (migration 0003)
Migration 0003 also adds `cases.compared_at` (null until the case is compared).

| Table | `veritas_app` grants | Notes |
|---|---|---|
| findings | SELECT, INSERT, UPDATE | Unique `(case_id, finding_key)`, where the key is `rule_id:signature`, makes re-runs upserts. Holds the three separate values `anomaly_score`, `evidence_confidence` and `priority`, plus `severity`, `explanation`, `limitations`, `coverage`, `status`, `active` and `ai_output_json`. |
| evidence_items | SELECT, INSERT, DELETE | One cited field: `extracted_field_id` (`ON DELETE SET NULL`), `document_id`, `page_number`, `bbox` or `location`, `value`, `normalized_value`, `confidence` and `role`. Replaced on a re-run, never edited. |
| finding_decisions | SELECT, INSERT | Append-only review history: actor, from and to status, and note. |
| investigator_comments | SELECT, INSERT | Append-only. |

Triggers (they run as the invoking role, so RLS applies to their lookups):
- `findings_require_evidence` (`enforce_finding_evidence()`): setting `confirmed_observation` without an evidence row raises `finding_requires_evidence`.
- `findings_ai_output_immutable` (`protect_finding_ai_output()`): any change to `ai_output_json` raises.
- `evidence_items_scope` (`enforce_evidence_scope()`): evidence must cite a document of the finding's own case, and a field of that document. Otherwise it raises `evidence_outside_case` or `evidence_field_mismatch`.

## Tables (migration 0004)
| Table | `veritas_app` grants | Notes |
|---|---|---|
| entities | SELECT, INSERT, DELETE | Derived per case. The id is UUIDv5 of (case, type, normalized name), so a rebuild keeps it. Unique `(case_id, type, normalized_name)`. `status` is `resolved` or `possible_duplicate`. |
| entity_mentions | SELECT, INSERT, DELETE | One per extracted field behind an entity (`ON DELETE CASCADE` from the field) |
| relationships | SELECT, INSERT, DELETE | `evidence_ids uuid[]` with `CHECK (cardinality(evidence_ids) > 0)`. The trigger `relationships_evidence` (`enforce_relationship_evidence()`) rejects any id that isn't an `extracted_fields` or `evidence_items` row of the same organization (`relationship_evidence_not_found`). `CHECK (type <> 'CONTRADICTS' OR finding_id IS NOT NULL)`. |
| outbox | SELECT, INSERT, UPDATE | Graph sync events (`case.replace`), written in the same transaction as the rebuild. Status `pending → processing → done`, or `dead` after the maximum attempts. Backoff through `available_at`. |

Owner-owned `SECURITY DEFINER` functions, executable only by `veritas_app`, used by the worker across tenants. They return ids or counts, never row contents:
- `outbox_claim(limit)` marks up to 100 due rows `processing` (`FOR UPDATE SKIP LOCKED`) and returns `(id, organization_id)`. Rows stuck in `processing` for 10 minutes are claimed again.
- `outbox_health()` returns counts by status.
- `graph_cases()` returns `(organization_id, case_id)` of live compared cases, for the reconciler.

Neo4j holds a derived copy. Nodes are labelled `:VeritasNode:Document|Entity|Finding`, and edges are typed by relationship type. Each node and edge carries `ns`, `organization_id` and `case_id`. There is a uniqueness constraint on `id` and an index on `(ns, organization_id, case_id)`. It can be rebuilt from Postgres at any time (`POST /cases/{id}/graph/rebuild`, or the reconciler).

Original files are not stored in Postgres. They live in object storage under `<organization_id>/…` and are never modified.

## Testing
- `tests/integration/test_migrations.py`: upgrade, downgrade, upgrade, then a model diff that must be empty.
- `tests/integration/test_rls.py`: role flags, RLS coverage of every table with `organization_id`, cross-tenant reads and writes, and the append-only audit log.
- `tests/integration/test_findings.py`: the three triggers, the append-only grants on decisions and comments, and the isolation of the four Phase 3 tables.
