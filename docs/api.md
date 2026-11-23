# API

The authoritative contract is [`backend/openapi.json`](../backend/openapi.json), generated from the FastAPI app and checked by `scripts/check_openapi.py` (the quality gate and the *api-contract* hook). Interactive docs: `/api/docs`.

## Conventions
- Base path `/api/v1`. JSON bodies. Bearer access tokens (`Authorization: Bearer …`).
- Errors use `application/problem+json`: `{type, title, status, detail, instance, request_id}`. Validation errors add `errors: [{loc, msg}]`.
- A resource of another organization is always **404**. An insufficient role in your own organization is **403**.
- Cursor pagination: `?limit=1..100&cursor=…` returns `{items, next_cursor}`.
- Every response carries `X-Request-ID`. Send your own to correlate logs.

## Endpoints (Phase 1)
| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | /auth/register | public | Creates the user, a new organization and an `org_admin` membership. 201 with a token pair. |
| POST | /auth/login | public | Rate-limited per IP and email (429 + `Retry-After`). Optional `organization_id` selects the organization. |
| POST | /auth/refresh | public | Rotates the refresh token. Reusing an old token revokes the whole session family. |
| POST | /auth/logout | public | Revokes the session family. Always 204. |
| GET | /auth/me | authenticated | User, active organization, role, permissions |
| GET | /organizations | authenticated | Organizations the caller belongs to |
| POST | /organizations | authenticated | Creates an organization with the caller as admin |
| GET | /organizations/{id} | org:read | Active organization only |
| PATCH | /organizations/{id} | org:update | Name, `retention_days` |
| GET | /organizations/{id}/members | members:read | |
| POST | /organizations/{id}/members | members:manage | Adds an existing user by email |
| PATCH | /organizations/{id}/members/{user_id} | members:manage | Changes the role. 409 if it would remove the last admin. |
| DELETE | /organizations/{id}/members/{user_id} | members:manage | Also revokes their sessions in the organization |
| GET | /audit-logs | audit:read | Newest first, paginated |
| GET | /stats/overview | stats:read | Computed from the organization's records. Unbuilt metrics return `available: false`. |
| POST | /system/ping-job | system:ping | Queues a real worker connectivity job (202) |
| GET | /jobs/{id} | jobs:read | |
| GET | /jobs/{id}/events | jobs:read | Server-sent events. Send `Last-Event-ID` to resume. |
| GET | /system/health | public | 200 or 503 with the database and Redis status |

## Endpoints (Phase 2)
| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | /cases | cases:read | Filters `status`, `priority`, `q` (literal match). Opaque cursor; a malformed cursor is 422. Counts per case. |
| POST | /cases | cases:write | `{title, objective, investigation_type, priority}` |
| GET / PATCH / DELETE | /cases/{id} | cases:read / write / delete | DELETE is a soft delete: the case and its documents disappear from every API, and originals are kept |
| POST | /cases/{id}/documents | documents:upload | Multipart `files` (up to 100). Per-file result `accepted`, `duplicate` or `rejected` with a reason, plus the processing `job_id` |
| GET | /cases/{id}/documents | documents:read | Documents with their stage records |
| POST | /cases/{id}/process | documents:process | Queues uploaded or failed documents (202). `job_id: null` when there is nothing to do |
| GET | /documents | documents:read | All documents of the organization. Filters `status`, `doc_type`, `q` (filename) |
| GET | /documents/{id} | documents:read | Metadata, SHA-256, detection reason, stages with metrics, `supersedes_id` for versions |
| GET | /documents/{id}/pages | documents:read | Text, lines with token boxes or locations, Docling tables, `coord_unit` |
| GET | /documents/{id}/extractions | documents:read | Latest run and its fields with full provenance |
| GET | /documents/{id}/preview | documents:read | 60 s signed URL to the original (audited `document.access`). `?page=n` for TIFF page images |
| POST | /documents/{id}/retry | documents:process | Failed documents only (otherwise 409). Resumes from the failed stage |
| GET | /files/{token} | signed link | Serves the bytes (audited `document.download`) with `nosniff` and a `sandbox` CSP. Tampered or expired links are 403 |

The processing job streams `queued`, `started`, `stage_started`, `stage_completed`, `stage_retry`, `document_completed` or `document_failed`, `progress`, and finally `succeeded`, through `GET /jobs/{id}/events`.

## Endpoints (Phase 3)
| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | /cases/{id}/compare | findings:run | 202 with `job_id`. Re-runs the comparison (Celery task `cases.compare`). Comparison also runs automatically at the end of every processing job. |
| GET | /cases/{id}/findings | findings:read | Active findings of the case, most severe first. `include_inactive=true` adds findings the latest run no longer detects. |
| GET | /findings | findings:read | Findings Center. Filters: `status`, `severity`, `priority`, `type`, `case_id`, `include_inactive`. Cursor pagination (`limit` ≤ 100). |
| GET | /findings/{id} | findings:read | Detail with evidence, decisions, comments and the immutable `ai_output_json` |
| GET | /findings/{id}/evidence | findings:read | Each item links `extracted_field_id`, `page_number`, `bbox` or `location`, and the cited `value` |
| PATCH | /findings/{id}/status | findings:review | `{status, note}`. A note is required for `dismissed` and `confirmed_observation` (422). 409 when confirming a finding without evidence, or when the status is unchanged. Appends a `finding_decisions` row and an audit entry. |
| POST | /findings/{id}/comments | findings:comment | 201. Append-only. |

Every finding carries three separate values: `anomaly_score` (magnitude, 0..1), `evidence_confidence` (lowest measured confidence of the cited fields, null if not measured) and `priority`. None of them is a probability of fraud. Statuses: `new, under_review, confirmed_observation, needs_more_evidence, dismissed, resolved`. A finding in another organization is a 404. `CaseOut` now has `compared_at`, and `finding_count` is null until the case has been compared.

The processing job adds `comparison_started` and `comparison_completed` (or `comparison_failed`) per case, and since Phase 4 each comparison summary includes `graph: {entities, relationships}`, and its result has a `comparisons` list with the counts of `created`, `updated` and `deactivated` findings, `rules_ran` and `rules_failed`.

## Endpoints (Phase 4)
| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | /cases/{id}/graph | graph:read | `{nodes, edges, source, total_nodes, total_edges}`. `types` is a comma-separated list of node kinds or entity types (`document,organization,shipment,transaction,finding`). `q` searches labels and keeps the matches' direct neighbours. The `X-Graph-Source` header is `neo4j`, or `postgres` while a sync is pending or Neo4j is unavailable. |
| POST | /cases/{id}/graph/rebuild | graph:rebuild | 202 `{entities, relationships}`. Rebuilds the case graph from Postgres in the request and queues the Neo4j sync. Audited as `graph.rebuild`. |
| GET | /entities/{id} | graph:read | The entity with every mention (document, field, value, page, bbox or location, confidence) |
| GET | /entities/{id}/relationships | graph:read | Edges touching the entity, with both ends' labels |
| GET | /relationships/{id}/evidence | graph:read | The `extracted_fields` and `evidence_items` behind an edge, each with its document, page and field id |

Every edge carries non-empty `evidence_ids`. `CONTRADICTS` edges also carry `finding_id`. Entities, relationships and graphs of another organization or of a deleted case are a 404. `GET /system/health` adds a `graph` section (`status`, `outbox_pending`, `outbox_dead`). It doesn't change the overall status, because the graph is served from Postgres when Neo4j is down.

## Endpoints (Phase 5)
| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | /documents/{id}/forensics | forensics:read | The latest forensic run, or `null` if the document hasn't reached the stage. Fields: `{id, document_id, pipeline_version, status (succeeded, partial or not_applicable), analysis_types, pdf_metadata, structure, limitations, started_at, finished_at, anomalies}`. Anomalies are sorted by severity, then page. |
| GET | /cases/{id}/forensics | forensics:read | One row per document of the case: `{document_id, filename, doc_type, mime_type, status, analysis_types, anomalies, medium, low, types}`. Documents with more medium anomalies come first. |

- Each anomaly has `{id, type, page_number, region, severity, explanation, metrics, requires_review}`.
- `region` is `[x0, y0, x1, y1]` with a top-left origin, in PDF points (pixels for image files), the same as field bboxes.
- `severity` is `info`, `low` or `medium`, never higher. The database enforces this with a CHECK constraint.
- `requires_review` is true for medium anomalies.
- `metrics` holds the measured values behind the anomaly. The keys `fields` and `field_id` hold the ids of the overlapping `extracted_fields` rows.
- Anomaly types:
  - `incremental_update`
  - `metadata_inconsistency`
  - `font_inconsistency`
  - `localized_compression_anomaly`
  - `version_difference`
  - `stamp_appearance_variation`
- Every run includes the limitation "A visual or structural inconsistency alone does not establish document alteration or forgery."
- Anomalies never create findings.
- A document or case of another organization, or of a deleted case, is a 404.

The processing job's stages are now `parse, classify, extract, validate, forensics`. The `forensics` stage's `stage_completed` event summary is `{status, analysis_types, anomalies, medium, compared_with_version, stamps_compared}`.

## Tokens
- Access tokens are HS256 JWTs valid for 15 minutes, with claims `sub, org, role, type=access, jti, iat, exp`. The role in the token is informational: every request re-reads the membership and role from the database.
- Refresh tokens are opaque random 256-bit strings, stored only as SHA-256 hashes and valid for 7 days.
