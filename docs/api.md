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

## Endpoints (Phase 6)
| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | /cases/{id}/investigate | investigations:run | `{objective}` (3–1000 chars). Returns 202 with the investigation (`queued`) and runs it in the worker. 409 if the case already has one in progress. Audited as `investigation.start`. |
| GET | /cases/{id}/investigations | investigations:read | The case's investigations, newest first |
| GET | /cases/{id}/evidence-requests | investigations:read | Evidence requested for the case, newest first |
| GET | /investigations/{id} | investigations:read | `status`, `budget` (limits), `usage` (iterations, tool calls, provider-reported tokens, `unmetered_calls`, elapsed seconds), `error`, `result.agents` (each agent's validated output), `result.report_draft` (after approval), `agent_runs` and `evidence_requests` |
| GET | /investigations/{id}/events | investigations:read | SSE of the persisted `agent_events` (`id` is the event `seq`; send `Last-Event-ID` to resume). Ends with `event: end` when the run pauses for review or finishes. |
| POST | /investigations/{id}/approve | findings:review | 202. Only from `awaiting_review` (otherwise 409). The worker then runs the report step. Audited as `investigation.approve`. |
| POST | /investigations/{id}/request-evidence | findings:comment | `{document_types, note}` returns 201. Blank types are dropped, and 409 if none is left. Audited as `investigation.request_evidence`. |

- Statuses: `queued`, `running`, `awaiting_review`, `approved`, `completed`, `failed` and `budget_exhausted`.
- Event types: `queued`, `investigation_started`, `agent_started`, `tool_called`, `tool_failed`, `tool_rejected`, `reference_rejected`, `output_invalid`, `agent_completed`, `agent_failed`, `awaiting_review`, `approved`, `report_started`, `evidence_requested`, `investigation_completed`, `investigation_failed` and `budget_exhausted`.
- Every citation stored in an agent output has resolved to a row of the same organization and case. Any citation that didn't was removed, and a `reference_rejected` event records it.
- Agents never change findings.
- An investigation of another organization, or of a deleted case, is a 404.

Since Phase 6, every request's transaction commits before the response is sent (`Depends(db_session, scope="function")`), so a client can read its own write immediately after a 2xx.

## Endpoints (Phase 7)
| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | /cases/{id}/reports | reports:create | `{format: pdf\|docx\|xlsx\|json, investigation_id?}` returns 202 (`queued`). The worker builds, verifies, renders and stores the report. An investigation must be completed and approved, otherwise 409. Audited as `report.request`. |
| GET | /cases/{id}/reports | reports:read | History, newest first: `format`, `status`, `sha256`, `size_bytes`, `error`, `created_by_email`, and `findings_total` / `findings_not_reviewed` as they were at generation |
| GET | /reports/{id} | reports:read | The above plus `model`, the verified content every format was rendered from |
| GET | /reports/{id}/download | reports:read | `{url, expires_at}`: a signed link valid for 60 s. 409 unless the report is `completed`. Audited as `report.access`. |
| GET | /report-files/{token} | signed link | The file, sent as an attachment with `X-Report-SHA256`. The stored file's hash is re-checked first. Audited as `report.download`. A document link is refused here (403), and a report link is refused on `/files` (403). |
| PATCH | /findings/{id}/assignee | findings:assign | `{user_id \| null}`. The user must be a member of the organization, otherwise 422. Audited as `finding.assign`. |
| POST | /findings/{id}/evidence-requests | findings:comment | `{document_types, note}` returns 201. Shown on the finding (`evidence_requests`), on the case (`/cases/{id}/evidence-requests`) and in reports. 422 if no type is left after trimming. Audited as `finding.request_evidence`. |

- `FindingSummary` gains `assignee_user_id`.
- `FindingDetail` gains `assignee_email` and `evidence_requests`.
- `EvidenceRequestOut` gains `finding_id`.
- A failed report's `error` lists every reference that didn't resolve, or a summary value missing from the content, separated by `; `.
- Reports, findings and requests of another organization, or of a deleted case, are a 404.

## Endpoints (Document Comparison Lab)
An original and a test document of the same case are compared: pages are aligned, text and pixels compared, and the strongest regions checked by the vision model. Results are differences for review, never verdicts.

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | /cases/{id}/comparisons/upload | comparisons:run + documents:upload | Multipart `original` and `test` (PDF, PNG, JPEG, TIFF). Both go through normal ingestion (magic bytes, SHA-256, duplicates, immutable storage) and a processing job. Returns 202 `{comparison, original, test, job_id}`; the comparison waits for processing. A rejected file is 422; two identical files are 409. A file already in the case is reused (`status: duplicate`). |
| POST | /cases/{id}/comparisons | comparisons:run | `{original_document_id, test_document_id}`, two different documents of this case, returns 202 (`queued`). Other file types are 422; a document of another case is 404. Audited as `comparison.create`. |
| GET | /cases/{id}/comparisons | comparisons:read | Newest first: `status` (`queued`, `waiting_for_documents`, `running`, `completed`, `failed`), `stage`, `progress` (0-100, persisted by the worker), `vlm_status` (`used`, `unavailable`, `failed`, `disabled`, `not_run`), `vlm_model`, `findings_count`, `findings_unreviewed`, filenames |
| GET | /comparisons/{id} | comparisons:read | The above plus `settings`, `summary` (both SHA-256s, page alignment method and SSIM per page, counts, method thresholds, vision-model calls, seconds, tokens, rejected boxes and proposals), `limitation`, `findings` and `exports` |
| POST | /comparisons/{id}/retry | comparisons:run | Only a `failed` comparison (else 409). Returns 202. Audited as `comparison.retry`. |
| PATCH | /comparisons/{id}/findings/{fid}/review | findings:review | `{status: confirmed_difference\|needs_more_evidence\|dismissed\|unreviewed, note}`. A note is required to confirm or dismiss (422). Appends to `comparison_reviews`; audited as `comparison.review`. |
| GET | /comparisons/{id}/findings/{fid}/reviews | comparisons:read | The append-only review history with actor emails |
| POST | /comparisons/{id}/exports | comparisons:run | `{kind: annotated_pdf\|annotated_images\|report_pdf\|findings_json}`, returns 202. Regenerates from the current rows (e.g. after review: dismissed differences aren't drawn). 409 unless the comparison is completed. The four kinds are also generated automatically on completion. |
| GET | /comparisons/{id}/exports | comparisons:read | Newest first: `kind`, `status`, `sha256`, `size_bytes`, `error` |
| GET | /comparison-exports/{id}/download | comparisons:read | `{url, expires_at}`, a signed link valid for 60 s; 409 unless completed. Audited as `comparison.export_access`. |
| GET | /comparison-files/{token} | signed link | The file as an attachment with `X-Export-SHA256`, after re-checking the stored hash. Audited as `comparison.export_download`. Document and report links are refused here (403), and export links are refused on `/files` and `/report-files` (403). |
| GET | /system/vlm-status | comparisons:read | `{enabled, configured, model, endpoint_host, reachable, model_available, error}` from the endpoint's `/models` list; sends no document data |

A finding (`ComparisonFindingOut`) has `number` (drawn on the annotated files), `type` (`text_changed`, `text_added`, `text_removed`, `visual_difference`, `vlm_observed_difference`, `page_added`, `page_removed`), `sources` (`ocr` for text-layer or OCR text, `cv`, `vlm`, `page`), `test_page` and `region`, `original_page` and `original_region` (each `[x0, y0, x1, y1]`, top-left origin, in its own page units and validated inside the page), `original_text`, `test_text`, `severity` (at most `medium`), `evidence_confidence`, `explanation`, `metrics` (`confidence_basis`, `extracted_fields` references, pixel and OCR measurements) and `vlm_assessment`. Comparisons, findings and exports of another organization are a 404.

## Endpoints and behavior (Phase 9)
| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | /system/health | none | Unchanged `status` (database and Redis decide it, and the container health check uses it). New `services`: `storage` (bucket reachable) and `worker` (Celery ping, worker count only). They are reported but never change `status`. |
| GET | /system/metrics | system:metrics (org_admin only) | Broker queue depth (global count) and this organization's document stages: succeeded, failed and other counts, and mean seconds of succeeded runs |
| GET | /system/models | stats:read | The configured OpenAI-compatible endpoint (host only), whether a key is set (never the key), and each text, vision and fallback model with `available` from the endpoint's `/models` list. `embeddings: not_built`. |

- **Rate limits (429 + `Retry-After`, problem+json):** `POST /cases/{id}/documents` and `POST /cases/{id}/comparisons/upload` share `VERITAS_UPLOAD_RATE_LIMIT_PER_MINUTE` (30) per member. `POST /cases/{id}/investigate` is limited by `VERITAS_INVESTIGATION_RATE_LIMIT_PER_MINUTE` (5) per member. Only requests that pass authentication and the permission check count. Redis down means 503 (fail closed).
- **Downloads:** `GET /files/{token}` opened directly is now `Content-Disposition: attachment` with a sanitized filename. The in-app viewer (`X-Veritas-Viewer: 1`) still gets an anonymous binary body. An `<img>` request (`Sec-Fetch-Dest: image`) for an image file is `inline`.

## Tokens
- Access tokens are HS256 JWTs valid for 15 minutes, with claims `sub, org, role, type=access, jti, iat, exp`. The role in the token is informational: every request re-reads the membership and role from the database.
- Refresh tokens are opaque random 256-bit strings, stored only as SHA-256 hashes and valid for 7 days.
