# Implementation progress

This file records only verified status. "Completed" means the listed tests were run and passed on the date shown. Statuses: Not Started, In Progress, Blocked, Completed, Needs Review.

**Environment used for verification (2026-11-23):** Windows 11, PowerShell 7, Docker 29.8.1 (Compose v5.5.1, 8 GB, 16 CPUs), Python 3.12 via uv 0.10.6, Node 24.14.1.

**Open assumptions (please confirm or change):**
- Hackathon category: **Frankenstein**.
- Scope: shipment-discrepancy vertical slice first.
- Model access: one OpenAI-compatible provider interface (hosted or local Qwen). No GPU assumed. Provider credentials aren't configured yet; they are needed from Phase 2 task 7 onward.

## Summary
| Phase | Status | Evidence |
|---|---|---|
| 0: Kiro setup | Completed | 10 steering files, 12 specs (36 files), 10 agents, 8 hooks. JSON valid. `.kiro` not ignored. |
| 1: Platform foundation | Completed | Quality gate 8/8 PASS (76 backend + 25 frontend tests). Playwright 2/2 against the stack. Smoke 9/9, including a clean-copy deployment with fresh volumes. Gitleaks clean. |
| 2: Ingestion and intelligence | Completed (live provider run done 2026-11-23 with local Ollama `qwen2.5:7b-instruct`) | Quality gate 8/8 PASS (204 backend + 30 frontend tests, 0 skipped, real PaddleOCR and Docling). Playwright 5/5 including the 7-document upload and the scanned invoice. Smoke 10/10 on the stack and on a clean deployment. Gitleaks clean. |
| 3: Cross-document intelligence | Completed (optional LLM interpretation not built) | Quality gate 8/8 PASS (251 backend + 37 frontend tests, 0 skipped). Demo case: exactly one `financial_discrepancy` of USD 20,000.00 with 5 evidence items, no quantity finding. Playwright 6/6, smoke 11/11 on the rebuilt stack. Gitleaks clean. |
| 4: Evidence knowledge graph | Completed | Quality gate 8/8 PASS (269 backend + 43 frontend tests, 0 skipped; 7 live tests run separately). Demo graph: one supplier entity from both spellings, 6 CONTRADICTS edges carrying the finding id, every edge backed by evidence (enforced by the database). Real Neo4j outage and recovery on the stack. Playwright 7/7, smoke 12/12, gitleaks clean. |
| 5–10 | Not Started | Specs written |

---

## Phase 0: Kiro setup
| Task | Status | Files | Verification |
|---|---|---|---|
| 0.1 Repository scaffold | Completed | `LICENSE` (MIT), `README.md` (pre-existing code: none), `.gitignore`, `.gitattributes`, `.env.example` | `git check-ignore -v .kiro .kiro/specs .kiro/steering .kiro/agents .kiro/hooks .kiro/settings` printed nothing (exit 1) |
| 0.2 Steering | Completed | `.kiro/steering/{product,tech,structure,coding-standards,ai-engineering,document-processing,security,testing,ui-design,data-governance}.md` | Front matter uses only documented `inclusion` modes (always ×3, fileMatch ×6, auto ×1). Loading confirmed in-session: Kiro injected `tech`, `structure`, `product`, `security`, `coding-standards`, `testing`, `ui-design` and `document-processing` when matching files were touched. |
| 0.3 Specs | Completed | `.kiro/specs/<12 features>/{requirements,design,tasks}.md` | All 36 files have content. Phase 1–2 specs in full detail. |
| 0.4 Custom agents | Completed | `.kiro/agents/*.md` (10) | Documented fields only (`name, description, tools, resources, permissions.rules, welcomeMessage`) |
| 0.5 Hooks | Completed | `.kiro/hooks/*.json` (8), created with Kiro's hook tool | All parse. Triggers: PostFileSave ×5, PostFileCreate, Stop, PostTaskExec. Observed firing in-session (security-review and test-suggestion prompts after file saves and creates). |
| 0.6 MCP | **Blocked (manual setup)** | none | Kiro's permission policy blocks agents from writing `.kiro/settings/`. The exact config is in `docs/kiro-usage.md` §5 for you to paste. |
| 0.7 Docs | Completed | `docs/architecture.md`, `docs/kiro-usage.md`, this file | |

## Phase 1: Platform foundation
Spec tasks ticked: `platform-foundation/tasks.md` 6/6, `authentication-rbac/tasks.md` 7/7.

| Task | Status | Key files | Tests |
|---|---|---|---|
| 1.1 Backend skeleton | Completed | `backend/app/core/{config,logging,errors,middleware}.py`, `app/main.py` | `unit/test_config.py` (8), `unit/test_permissions_and_errors.py` (7), `integration/test_health.py` (4) |
| 1.2 Database and RLS | Completed | `app/models/*`, `migrations/versions/0001_foundation.py`, `migrations/rls.py`, `infrastructure/docker/postgres/init/01-roles.sh` | `integration/test_migrations.py` (up, down, up, no drift), `integration/test_rls.py` (7) |
| 1.3 Authentication | Completed | `app/core/security.py`, `app/services/identity/{auth,rate_limit}.py`, `app/api/v1/auth.py` | `unit/test_security.py` (8), `integration/test_auth.py` (15), Hypothesis hashing properties |
| 1.4 Organizations and RBAC | Completed | `app/core/permissions.py`, `app/api/deps.py`, `app/services/identity/{organizations,members}.py`, `app/services/audit/service.py` | `integration/test_organizations.py` (6), `integration/test_rbac_matrix.py` (5 roles × 7 endpoints), `integration/test_tenant_isolation_property.py` (Hypothesis) |
| 1.5 Redis, Celery, jobs, SSE | Completed | `app/services/jobs/{service,runner}.py`, `app/workers/*`, `app/api/v1/system.py` | `integration/test_jobs_and_stats.py` (7), `integration/test_job_sequence_property.py` (Hypothesis), `property/test_invariants.py` (state machine, backoff) |
| 1.6 Overview stats | Completed | `app/services/stats/overview.py` | `test_overview_stats_are_computed_from_records` (zeros, then counts, isolation) |
| 1.7 Frontend foundation | Completed | `frontend/` (Vite, React 18, TS strict, Tailwind tokens, TanStack Query, Zustand, typed client generated from `openapi.json`) | `src/app/navigation.test.tsx` (11 labels in order, 8 pending states, redirect), `src/services/api.test.ts` (problem+json, single-flight refresh, sign-out, SSE parser) |
| 1.8 Connected flows | Completed | `features/{auth,overview,audit,settings}` | Vitest: `auth.test.tsx` (4), `OverviewPage.test.tsx` (4), `MembersPanel.test.tsx` (3). Playwright: `tests/e2e/foundation.spec.ts` (2) against the real stack. |
| 1.9 Docker Compose | Completed | `docker-compose.yml`, `docker-compose.prod.yml`, `infrastructure/docker/{backend,frontend}.Dockerfile`, `frontend/nginx.conf`, `scripts/smoke.{ps1,sh}`, `docs/deployment.md` | `docker compose config` (dev and prod) valid. Stack healthy. `smoke.ps1` 9/9. |
| 1.10 Verification | Completed | `scripts/quality-gate.{ps1,sh}`, `backend/scripts/{export,check}_openapi.py` | See below |

### Test results (2026-11-23)
| Check | Result |
|---|---|
| `scripts/quality-gate.ps1` | **8/8 PASS**: ruff format, ruff check, mypy (strict, 46 files), pytest **76 passed, 0 skipped**, OpenAPI contract, tsc, eslint, vitest **25 passed** |
| Playwright e2e (`npx playwright test`, full stack via Nginx) | **2 passed**: register → live overview → real worker job over SSE → pending section → settings rename → audit log → reload restore → sign out and in; plus the wrong-password message |
| Smoke (`scripts/smoke.ps1`) on the running stack | **9/9 PASS** |
| Clean deployment: committable files only, a new `.env` from `.env.example`, fresh volumes (Compose project `veritas-clean`) | Healthy in 32 s (warm build cache). Smoke **9/9 PASS**. |
| Gitleaks (official container, committable files) | **No leaks.** One false positive (a deliberately wrong test password) marked inline with `gitleaks:allow`. |
| Migration cycle | upgrade → downgrade → upgrade, `compare_metadata` diff empty, `alembic check` "No new upgrade operations detected" |

### Defects found and fixed during Phase 1 (each covered by a test)
1. **Unattributed audit rows rejected by RLS.** `INSERT … RETURNING` applies the SELECT policy, so failed logins for unknown emails returned 500. Fixed with `implicit_returning=False` on `audit_logs` (keeping null-org rows unreadable by tenants). Tests: `test_unattributed_audit_rows_are_not_readable_by_tenants`, `test_wrong_password_and_unknown_email_give_same_401`.
2. **Rate limiter crash on the limited path.** `max()` over an async generator. Caught by mypy and fixed. Test: `test_login_rate_limit_returns_429`.
3. **Worker crash:** `celery` without the `[redis]` extra lacked `packaging`. Fixed the dependency. Verified by smoke and Playwright.
4. **502 after the backend was recreated:** Nginx cached the old container IP. Fixed with Docker DNS `resolver` and a variable `proxy_pass`. Verified by smoke.
5. **Windows `localhost` → IPv6 stalls** (2 s per connection). Switched to `127.0.0.1` in `.env.example` and documented it.

### Known limitations (Phase 1)
- Refresh token is stored in `localStorage` (documented trade-off; httpOnly cookie planned in enterprise-security).
- Two tabs refreshing at the same moment are treated as token reuse (strict, signs both out).
- Tokens are organization-scoped. Switching organizations means signing in with `organization_id`. The UI has no organization switcher yet.
- Retention days can be set, but the purge job is planned for enterprise-security task 7.
- Test-only `ResourceWarning`s for the cached Redis client at session teardown (48 warnings, no failures).
- `pip-audit`, `npm audit` and semgrep aren't run yet (enterprise-security task 6). npm reported that `recharts@2` and `eslint@9` are past active support. Upgrades are tracked for Phase 8.
- The clean-deployment check used a warm Docker build cache. A cold build downloads the base images (pulled earlier in this session).
- Leftover test volumes `veritas-clean_pgdata` and `veritas-clean_redisdata` exist from the clean-deployment check. They are safe to delete with `docker volume rm veritas-clean_pgdata veritas-clean_redisdata`.

### Remaining work from Phase 1 (still open)
- **You:** create `.kiro/settings/mcp.json` from `docs/kiro-usage.md` §5, and set `VERITAS_RO_DATABASE_URL` in your environment for the Postgres MCP server.
- **You:** confirm the category and scope assumptions, and provide model provider details (`VERITAS_LLM_BASE_URL`, `VERITAS_LLM_MODEL`, `VERITAS_VLM_MODEL`, API key) for Phase 2 extraction.
- Phase 2 spec tasks: `document-ingestion/tasks.md` (5) and `document-intelligence/tasks.md` (10), all Not Started.

## Phase 2: Document ingestion and multimodal intelligence
Spec tasks ticked: `document-ingestion/tasks.md` 5/5, `document-intelligence/tasks.md` 10/10. Both files include implementation notes on the design deviations below.

| Task | Status | Key files | Tests |
|---|---|---|---|
| 2.1 Storage and worker image | Completed | `app/integrations/storage/{base,s3_store}.py`, `infrastructure/docker/backend.Dockerfile` (api and worker targets), `scripts/warm_models.py`, Compose `objectstore` and `models` volume | `test_originals_are_never_overwritten`, `test_filenames_are_metadata_only`, worker image built and warmed in Docker |
| 2.2 Synthetic samples | Completed | `backend/scripts/{generate_samples,sample_content}.py`, `sample-data/` (7 PDFs and 8 variants, every page labelled SYNTHETIC DEMONSTRATION DATA) | Deterministic (identical manifest hash on re-run); every file parsed in `tests/unit/test_parsing.py` |
| 2.3 Cases, upload, validation, duplicates | Completed | `migrations/versions/0002_documents.py`, `app/services/{cases,ingestion}/`, `app/api/v1/cases.py` | `tests/unit/test_ingestion_detect_archive.py` (26, Hypothesis traversal), `tests/integration/test_cases_and_upload.py` (12, Hypothesis dedupe) |
| 2.4 Classification | Completed | `app/services/classification/rules.py` | All 7 samples and every variant classify correctly; unrelated text gives `unknown` |
| 2.5 Parsing and OCR | Completed | `app/services/parsing/{model,pdf,office,layout,dispatch}.py`, `app/services/ocr/`, `app/integrations/ocr/paddle.py` | `tests/unit/test_parsing.py` (23, real PaddleOCR and Docling), Hypothesis offset and transform round trips |
| 2.6 Structured extraction | Completed (live provider **Blocked**) | `app/services/extraction/{fields,normalize,verify,result,rules,llm,validation}.py`, `app/integrations/llm/` | `tests/property/test_normalize.py` (20), `tests/unit/test_extraction.py` (33: ground truth, anti-fabrication, prompt-injection placement, replay, retries and fallback) |
| 2.7 Async pipeline | Completed | `app/workflows/document_pipeline.py`, `app/workers/document_tasks.py`, `execute_streaming_job` in `app/services/jobs/runner.py` | `tests/integration/test_pipeline.py` (13): 7-document case to ground truth, all 8 variants, no duplicates on re-run, failure then retry resumes, input errors don't retry |
| 2.8 Read APIs | Completed | `app/services/documents/service.py`, `app/api/v1/documents.py`, `app/core/signing.py` | Signed preview (tampered or expired 403, other org 404), cross-org 404 on 10 endpoints, direct-SQL RLS on 6 new tables |
| 2.9 Frontend | Completed | `features/investigations/*`, `features/documents/*`, `features/viewer/*` (PDF.js, image and parsed views, overlays, fields panel), `components/Dropzone.tsx` | Vitest 30 (7 files); Playwright `tests/e2e/documents.spec.ts` and `screenshot.spec.ts` |
| 2.10 Verification | Completed | `scripts/smoke.{ps1,sh}` (document pipeline check added), `docs/ai-pipeline.md` (measurements) | See below |

### Test results (2026-11-23, final code)
| Check | Result |
|---|---|
| `scripts/quality-gate.ps1` | **8/8 PASS**: ruff format and check, mypy strict (92 files), pytest **204 passed, 0 skipped** (3 min, real PaddleOCR and Docling), OpenAPI contract, tsc, eslint, vitest **30 passed** |
| Playwright on the running stack | **5/5**: 7-document shipment case uploaded through the UI and processed by the real worker, with the extracted totals and pages checked (48,000 ×3, 68,000 ×2, customs on page 2) and the evidence box on the rendered PDF; scanned invoice through OCR; Phase 1 flows; viewer screenshot |
| Smoke (`scripts/smoke.ps1`) | **10/10** on the stack, including upload → worker → extraction of USD 48,000 with a box |
| Clean deployment (committable files, new secrets, empty volumes including the model cache) | Healthy in **384 s** (includes the first model download); smoke **10/10** |
| Gitleaks | **0 findings** (one false positive removed by renaming code, not suppressed) |
| Visual check | `docs/screenshots/viewer-customs-value.png`: the boxes sit exactly on "USD 68,000.00", "USD" and "CIF Long Beach" on page 2 |

Measured timings are in `docs/ai-pipeline.md`: text-layer PDF parse 2.0 s mean, scanned PDF OCR 12.0 s per page, extraction 60 ms, full 7-document case about 22 s.

### Defects found and fixed during Phase 2 (each covered by a test)
1. **Deskew rotated blank pages by −5.5°**: a flat projection profile picked an arbitrary extreme angle. Rotation now requires a clear improvement over 0°. Test: `test_preprocess_keeps_image_size`.
2. **Pagination repeated page 1**: the ISO timestamp in the cursor contains `+`, which becomes a space in a query string, and the server silently ignored the unreadable cursor. Cursors are now opaque base64url, and a malformed cursor is 422. Tests: `test_case_pagination`.
3. **Concurrent duplicate upload would return 500** (unique violation). It now uses a savepoint and returns `duplicate`. Found in the hook-triggered security review.
4. **Broken `cv2` after a dependency change**: two OpenCV distributions (`opencv-python-headless` 5.1 from Docling's unused rapidocr, and `opencv-contrib-python` 4.10 from PaddleX) shared the same `cv2` package. Fixed with a single build and a uv override that drops rapidocr. Verified by the full OCR suites.
5. **PDF.js worker blocked in the browser**: Nginx served `.mjs` as `application/octet-stream`, and `nosniff` then blocked the module. `.mjs` is now served as `text/javascript`. Verified by Playwright.
6. **MinIO image unavailable**: the project was archived and its images removed. Replaced with SeaweedFS (server) and boto3 (client).
7. **TIFF not viewable in browsers**: TIFF frames are now stored as derived PNG artifacts behind artifact-scoped signed links. Test: the TIFF case in `test_every_format_variant_processes`.

### Known limitations (Phase 2)
- ~~Model provider not configured (Blocked).~~ **Resolved on 2026-11-23** with the local Ollama model `qwen2.5:7b-instruct`. Live runs on 15 documents with 0 invalid outputs; one claim was rejected by verification and replaced by the verified rules value. `tests/live` gives 7 passed. Details and timings are in `docs/ai-pipeline.md`. The merge of model and rules values moved to `app/services/extraction/merge.py` (unit and property tests), and it now records each rejected claim and substitution in the run notes.
- **VLM page-image extraction is not implemented.** The provider path sends text only (text layer or OCR output).
- The rules extractor relies on printed labels such as "Invoice Total:". Documents that use unknown labels give `null` / `uncertain`, which is safe but incomplete. That gap is what the provider path is meant to close.
- Language detection is a small English heuristic (`en` or unknown).
- EML attachments are listed, not processed.
- Docling's and OCR's timeouts can't stop a running thread. The stage is marked failed, and the thread finishes in the background.
- Classification confidence is a rule-match ratio, labelled as such. It isn't a probability.
- The worker image is about 4.5 GB, and its first start needs internet access to download models.
- The OCR tests take about 1 minute of the 3-minute backend run on CPU.

### Next (Phase 3: cross-document intelligence)
Comparison rules (currency-aware amounts, same-role dates, quantities, references, fuzzy parties), findings and evidence items linked to `extracted_fields`, the immutable `ai_output_json`, the evidence-required trigger, missing-document detection, and the Findings Center UI. Acceptance: exactly one `financial_discrepancy` of USD 20,000 with 5 evidence items, and no quantity finding.

## Phase 3: Cross-document intelligence
Spec tasks ticked: `cross-document-intelligence/tasks.md` 7/7. The spec's migration number was corrected from 0004 to 0003, and `design.md` was updated to match what was built. `evidence-explorer` tasks 3 and 6 are **partly** done (see limitations) and are not ticked.

| Task | Status | Files | Verification |
|---|---|---|---|
| 3.1 Migration 0003 | Completed | `migrations/versions/0003_findings.py`, `app/models/findings.py`, `cases.compared_at` | Migration cycle test; trigger and grant tests in `test_findings.py`; applied on the Docker database (`0002 -> 0003`) |
| 3.2 Names | Completed | `app/services/entity_resolution/names.py` (rapidfuzz, justified in `tech.md`) | `tests/property/test_names.py` (6) |
| 3.3 Financial and quantity rules | Completed | `app/services/comparison/rules/{financial,quantity}.py`, `model.py`, `engine.py` | `tests/property/test_comparison_properties.py` (5), `tests/unit/test_comparison_rules.py` |
| 3.4 Other rules | Completed | `rules/{references,identity,duplicates,dates,missing}.py` | Positive and negative unit cases per rule (20 rule tests in total) |
| 3.5 Risk scoring | Completed | `app/services/risk/scoring.py` | `tests/property/test_scoring.py` (10), including a scan that no `fraud_probability`/`fraud_score` exists in `app/` |
| 3.6 Persistence, service, API | Completed | `comparison/{persist,service}.py`, `findings/service.py`, `api/v1/findings.py`, `workers/comparison_tasks.py`, pipeline hook in `workflows/document_pipeline.py`, permissions `findings:{read,run,comment}` | `tests/integration/test_findings.py` (6), RBAC matrix (+7 endpoints), stats test |
| 3.7 Findings Center UI | Completed | `frontend/src/features/findings/*`, case workspace panel, investigations count, routes | `findings.test.tsx` (6), Playwright demo flow |
| 3.8 Verification | Completed | `scripts/smoke.{ps1,sh}` (comparison check), `docs/{api,database,ai-pipeline,architecture}.md`, `.env.example` | See below |

### Test results (2026-11-23, final code)
| Check | Result |
|---|---|
| Quality gate | 8/8 PASS: ruff format, ruff check, mypy (115 files), pytest **251 passed, 0 skipped** (181 s), OpenAPI contract, frontend typecheck, lint, Vitest **37 passed** |
| Demo case, integration (real pipeline, Postgres, S3) | One finding only: `financial_discrepancy`, difference `20000.00` USD, 5 evidence items (PO, invoice and receipt at 48,000; customs declaration page 2 and insurance certificate at 68,000). Each `extracted_field_id` resolves to the cited field with the same value, page and bbox. Anomaly 0.294, evidence confidence 1.000, severity high, priority high. |
| Re-run | Same finding id, status `under_review` kept, evidence ids and `ai_output_json` unchanged, `created=0 updated=1` |
| Review | 422 without a note for `dismissed`; confirm with note recorded with actor; 409 on the unchanged status; 409 on confirming an absence finding; comment stored; audit `finding.review` and `finding.comment` |
| Database integrity (as `veritas_app`) | Trigger errors `finding_requires_evidence`, `ai_output_json_is_immutable`, `evidence_outside_case` (other case of the same org, and another org's document); `permission denied` for UPDATE/DELETE on decisions and comments and DELETE on findings |
| Tenant isolation | Another org gets 404 on all 6 finding and case endpoints, an empty list, and no rows in the 4 tables; nothing is visible without a tenant |
| Playwright (Docker stack via Nginx) | 6/6: the 7-document case shows exactly one finding; detail with 5 evidence rows; "Open at source" opens the customs declaration at page 2 with the 68,000 box; a decision is recorded in the history; overview shows 1 finding to review and 1 high-priority finding |
| Smoke (`scripts/smoke.ps1`) | 11/11, including the new comparison check (invoice + customs declaration give USD 20,000.00 across 2 documents) |
| Comparison timing | 19 runs on the stack: mean 75 ms, max 159 ms (in `docs/ai-pipeline.md`) |
| Gitleaks (official container, 357 committable files) | No leaks |

### Defects found and fixed during Phase 3
1. **Import-time crash in the rule model**: the `FindingDraft.field` attribute shadowed `dataclasses.field`, so the module failed to load. Caught by the first test run; the import is aliased.
2. **Date-order rule crashed on any match**: field observations hold dicts and can't be placed in a set. Caught by `test_payment_before_invoice_is_informational`; deduplicated by field id.
3. **Socket exhaustion in the test suite on Windows** (`WinError 10055` in `test_persisted_event_seq_is_gapless_and_increasing`, which Hypothesis reported as flaky): tests used `NullPool`, opening a new connection (with an SSL attempt) for every session. Tests now use the production pool. The tenant setting is transaction-local, so it can't leak between pooled sessions. The full suite passed twice afterwards, and the backend run went from 318 s to 181 s.
4. mypy caught incorrect `Select` typing in the findings service before any test ran.

Earlier assertions that expected the "Available in a later phase" state for findings (Phase 1 stats test, overview Vitest, investigations Vitest, foundation Playwright) were updated to the real values. The foundation test now checks a section that is still pending (Reports) for that state.

### Known limitations (Phase 3)
- **Optional LLM interpretation (requirement 6) is not built.** Every finding comes from a deterministic rule and says so (`detector = "rules"`, `model = null`). No provider credentials are configured.
- **Graph outbox** events are not written yet; they belong to the evidence-knowledge-graph spec (Phase 4).
- **Evidence Explorer, partly done:**
  - Built: an evidence link opens the document at the cited field and page.
  - Not built: role-coloured highlights (cyan/red) in the viewer, side-by-side compare, investigator assignment and evidence requests.
- Severity thresholds (10% and 2%), the name threshold (0.85) and the 0.9 confidence cut for priority are fixed heuristics, documented on every finding's rationale. The two thresholds are configurable through `VERITAS_AMOUNT_TOLERANCE` and `VERITAS_NAME_SIMILARITY_THRESHOLD`.
- The missing-document rule only knows the `international_shipment` case type.
- When a document is reprocessed, its old fields are deleted. Until the comparison that runs at the end of the same job finishes, evidence items keep their snapshot values with a null `extracted_field_id`, and the UI says so.
- The column name `ai_output_json` comes from the spec. In this phase it holds the rule engine's output, not a model's.

### Next (Phase 4: evidence knowledge graph)
Neo4j projection of entities (parties, documents, references, shipments) through a transactional outbox, with every edge carrying an `evidence_id`, organization-scoped queries, and the Intelligence Graph UI (React Flow).

## Local model provider (2026-11-23, after Phase 3)
You provided local Ollama models. `qwen2.5:7b-instruct` is now configured in `.env` (git-ignored), and the extraction path runs live. The worker reaches Ollama through `host.docker.internal`, with an `extra_hosts` mapping for Linux. Results are in `docs/ai-pipeline.md`.
- 15 documents ran live, with 0 invalid outputs. The one rejected claim was the insurance certificate's `68000.00` for a printed `USD 68,000.00`. It was replaced by the verified rules value, and the run notes record it (`app/services/extraction/merge.py`).
- `tests/live` passed 7/7 (`pytest -m live`). Live tests are deselected from the gate by `addopts`.
- The viewer now names the text a model value was verified on, for example "Model, verified on OCR (PaddleOCR)".
- Not used:
  - the vision model `qwen2.5vl:7b` (page-image extraction isn't built);
  - the BGE embedding and reranker models (they belong to a later search phase);
  - the `-cloud` Ollama models, which would send document text off the machine.

## Phase 4: Evidence knowledge graph
Spec tasks ticked: `evidence-knowledge-graph/tasks.md` 6/6. The spec's migration number was corrected from 0006 to 0004, and `design.md` was updated to the built design.

| Task | Status | Files | Verification |
|---|---|---|---|
| 4.1 Migration 0004 | Completed | `migrations/versions/0004_graph.py`, `app/models/graph.py` | Migration cycle; RLS coverage; trigger tests |
| 4.2 Entity resolution | Completed | `app/services/entity_resolution/resolve.py` | `tests/unit/test_entity_resolution.py` (4, including an order-independence property) |
| 4.3 Projection | Completed | `app/services/graph/projection.py` | `tests/unit/test_graph_projection.py` (4, including the evidence and determinism property) |
| 4.4 Neo4j, outbox, reconciler | Completed | `app/integrations/graph/neo4j_store.py`, `app/services/graph/{service,sync}.py`, `app/workers/graph_tasks.py`, Compose `neo4j` service and worker `-B` | `tests/integration/test_graph.py` (7); `scripts/graph-outage-check.ps1` on the stack |
| 4.5 Graph API | Completed | `app/api/v1/graph.py`, `app/services/graph/queries.py`, `app/schemas/graph.py`, health `graph` section, permissions `graph:read` / `graph:rebuild` | `test_graph.py`, RBAC matrix (+5 endpoints), health test |
| 4.6 Intelligence Graph UI | Completed | `frontend/src/features/graph/*` (React Flow, dagre, list view, details panel), "Open graph" link from the case | `graph.test.tsx` (6), Playwright demo flow |

### Test results (2026-11-23, final code)
| Check | Result |
|---|---|
| Quality gate | 8/8 PASS: ruff, mypy (128 files), pytest **269 passed, 0 skipped, 7 live deselected** (200 s), OpenAPI contract, frontend typecheck, lint, Vitest **43 passed** |
| Demo graph (real pipeline, Postgres, Neo4j) | The organizations are ABC Imports Inc., Global Trading Ltd (7 mentions; "GLOBAL TRADING LIMITED" resolves to it) and Meridian Marine Insurance Co. There is one shipment, SHIP2049. The supplier has an ISSUED_BY edge from the invoice and an ASSOCIATED_WITH edge from the customs declaration (as exporter). There are 6 CONTRADICTS edges (three documents at 48,000 against two at 68,000), each carrying the finding id. There are 5 SUPPORTS edges. Every evidence id resolves. |
| Database rule | Inserting a relationship with no evidence (`evidence_required`), with an unknown evidence id (`relationship_evidence_not_found`), or a CONTRADICTS edge without a finding is refused |
| Sync | Neo4j nodes and edges equal the Postgres graph after the drain. While a sync is pending, or Neo4j fails, the API answers from Postgres. A rebuild keeps every id. A row is dead after the maximum attempts and reported in health. The reconciler repairs drift and removes a deleted case's subgraph. |
| Real outage (`scripts/graph-outage-check.ps1`, Docker stack) | With Neo4j stopped: health `graph.status = error`, 1 pending row, the API served the same 10 relationships from Postgres. 16 s after restart the row was applied; 0 pending, 0 dead. |
| Isolation | Another organization gets 404 on all 5 graph endpoints, an empty Neo4j read for the same case id, and no rows in the 4 new tables |
| Playwright (stack with Ollama and Neo4j) | 7/7. The demo flow continues into the graph: it waits for the Neo4j copy, highlights the 6 contradictions, shows an edge's evidence, and opens the customs declaration at page 2. A screenshot is saved as `docs/screenshots/intelligence-graph.png`. |
| Smoke (`scripts/smoke.ps1`) | 12/12, including the new graph check (synced to Neo4j in 2–6 s) |
| Sync latency | 48 outbox rows on the stack: mean 5.1 s from write to Neo4j, max 34.8 s (the row written during the outage check) |
| Gitleaks (387 committable files) | No leaks |

### Defects found and fixed during Phase 4
1. **Tests would have deleted the stack's graphs.** The reconciler removes Neo4j subgraphs whose case isn't in its Postgres. Integration tests share the Neo4j container with the running stack, so a test run would have removed the stack's data. Every node and edge now carries a namespace (`VERITAS_NEO4J_NAMESPACE`), every query filters on it, and tests use a random one. This was found by reviewing the reconciler before its tests were written.
2. **Finding status would go stale in Neo4j.** Review status changes outside comparisons, but it was copied into the graph. It is no longer stored there; the UI reads it from the finding.
3. **Empty minimap.** The React Flow minimap rendered as an empty grey box in the dark theme. Found on the screenshot and removed.
4. **Provenance gap in the viewer for model values.** The label said only "Model provider", hiding whether the value was verified on the text layer or on OCR. Found when two end-to-end assertions failed with the model enabled. The label now names the verification source, with a unit test.
5. mypy found Neo4j driver parameter typing issues, and a live-run environment variable leaked into one gate run (`VERITAS_LAYOUT_ENABLED=false`). The variable was cleared, and the gate was rerun clean.

### Known limitations (Phase 4)
- Entity types person, address, bank account, product and contract aren't built, because the field catalogue doesn't extract those values yet. `BELONGS_TO` and `DERIVED_FROM` are allowed types that no rule produces yet.
- The graph is rebuilt per case at each comparison. That is fast at this scale: the rebuild runs inside the comparison (under 0.2 s for the demo), and the Neo4j replace takes seconds.
- With more than one worker, beat must run in only one of them (documented in `docs/deployment.md`).
- Leftover Docker volumes from earlier clean-deploy checks (`veritas-clean*`) still exist.

### Next (Phase 5: document forensics)
PDF structure analysis (incremental updates, metadata, fonts, producer history), visual analysis with OpenCV (stamp and signature regions, copy-move hints), version comparison, results stored separately from extraction with their limitations, and the Forensics Lab UI.

## Loose ends from Phases 2–4 (In Progress, not verified)
Started 2026-11-23. During this work the sandbox lost access to `uv`, `node`, `npm`, `docker` and `pwsh` (Windows PowerShell 5.1, user profile unreadable), so **none of the changes below have been tested yet**.
- **Written:** optional fields `supplier_address` and `buyer_address` (value type `address`), `goods` (value type `product`) and `bank` (party).
  - The fields are in `app/services/extraction/fields.py`.
  - The normalizers `normalize_address` and `normalize_product` are in `normalize.py`.
  - The schemas are in `validation.py`.
- **Written:** address, product and bank entities in `entity_resolution/resolve.py`, and `BELONGS_TO` address→party edges backed by both fields in `graph/projection.py`. The UI type filter now has Addresses and Products.
- **Written, not run:** the tests in `tests/property/test_normalize.py`, `tests/unit/test_entity_resolution.py` and `tests/integration/test_graph.py`.
- **Not started:** page-image extraction with the vision model (`qwen2.5vl:7b`).
- **Moved to Phase 6:** the BGE embedding and reranker models (retrieval).
- **Blocked:** the first git commit and push to `github.com/OWAIS086-web/Veritas-Ai`. Git in the sandbox reports "dubious ownership", and pushing needs the user's credentials. The user runs it from their own terminal.
