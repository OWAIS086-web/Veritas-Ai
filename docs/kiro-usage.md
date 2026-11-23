# How VERITAS AI uses Kiro

This document is part of the Kiroween 2026 submission. It explains how Kiro's features shaped the build, and it is updated at the end of each phase. Nothing here describes work that has not been done. The current record covers Phases 0–5.

## Surfaces used
- **Kiro IDE** (Autopilot mode) for the whole build: specs, steering, hooks, custom agents and implementation.

## 1. Spec-driven development
Twelve feature specs live in `.kiro/specs/`. Each has `requirements.md` (user stories and EARS acceptance criteria such as *"WHEN … THE SYSTEM SHALL …"*), `design.md` (components, data model, APIs, failure handling, tests) and `tasks.md` (dependency-ordered tasks with measurable done conditions and requirement ids).

| Spec | Phase |
|---|---|
| platform-foundation, authentication-rbac | 1 |
| document-ingestion, document-intelligence | 2 |
| cross-document-intelligence | 3 |
| evidence-knowledge-graph | 4 |
| document-forensics | 5 |
| autonomous-investigation | 6 |
| evidence-explorer, reporting | 7 |
| enterprise-security, observability-testing | 9 (cross-cutting) |

**How we used them:**
- The specs were written before any application code.
- Each task's "Done when" line names the tests that prove it.
- A checkbox is ticked only after those tests pass, and the run output is recorded in `docs/implementation-progress.md`.
- The *final quality gate* hook runs on `PostTaskExec`, so completing a task triggers the full gate automatically.

**Spec versus vibe coding:** see §8 for concrete Phase 1 examples.

## 2. Steering strategy
Ten files in `.kiro/steering/` use three inclusion modes, so the always-on context stays small:

| File | Mode | Why |
|---|---|---|
| product.md, tech.md, structure.md | `always` | Kiro's foundation files: mission, hard rules, stack and architecture are needed on every request |
| coding-standards.md | `fileMatch` (`**/*.py`, `**/*.ts`, `**/*.tsx`) | Only when touching code |
| ai-engineering.md | `fileMatch` (agents, LLM, workflows, extraction) | Anti-fabrication and prompt-injection rules where models are called |
| document-processing.md | `fileMatch` (ingestion, ocr, parsing, extraction, forensics, workers) | Pipeline and provenance rules |
| security.md | `fileMatch` (core, api, storage, ingestion, identity, migrations) | Tenant isolation and auth rules exactly where they matter |
| testing.md | `fileMatch` (tests) | Quality gates and the no-skip rule |
| ui-design.md | `fileMatch` (`frontend/src/**`) | Design tokens and UX states |
| data-governance.md | `auto` (description-matched) | Provenance and audit rules, loaded when a request mentions findings, evidence or reports |

`structure.md` embeds `#[[file:docs/architecture.md]]`, so the architecture doc stays the single source of truth.

**Effect observed:** the `fileMatch` files loaded exactly when their paths were touched. For example, `security.md` loaded on `app/core/db.py`, `testing.md` on `tests/**`, and `ui-design.md` on `frontend/src/**`. The always-on context stayed at three files. See §8 for the RLS design correction that steering triggered.

## 3. Custom agents
Ten agents live in `.kiro/agents/*.md` (YAML front matter for config, the body as the system prompt). Steering is **not** inherited automatically by custom agents, so each agent lists only its relevant steering files under `resources`. That keeps each agent well under the limit of 32 files and 100,000 characters.

| Agent | Tools | Write scope (`permissions.rules` fs_write allow) | Notable restriction |
|---|---|---|---|
| document-intelligence-specialist | read, write, shell | services/{ocr,parsing,extraction,classification}, integrations/ocr, tests | Never invents values or confidence |
| computer-vision-forensics-specialist | read, write, shell | services/forensics, tests | No authenticity or fraud verdicts |
| backend-architect | read, write, shell | backend/** | No logic in handlers, respects the module table |
| frontend-engineer | read, write, shell | frontend/** | No fake data, every button works |
| investigation-workflow-engineer | read, write, shell | agents, workflows, integrations/llm, tests | Agents can't change finding status |
| database-architect | read, write, shell | models, migrations, postgres init, tests | `alembic downgrade` is `ask`; DROP and TRUNCATE are denied |
| security-reviewer | read, shell (scanners only) | none (fs_write denied) | Reports, never edits |
| test-engineer | read, write, shell | test files only | Never weakens or skips tests |
| devops-engineer | read, write, shell | infrastructure, compose, Dockerfiles, scripts | `docker compose down` is `ask`; volume deletion denied |
| product-quality-reviewer | read | none (all writes and shell denied) | Never accepts "should work" as evidence |

Every agent with shell access also has deny rules for `rm -rf*`, `git push --force*`, `git reset --hard*`, `sudo *`, `del /s*` and `Remove-Item -Recurse*`. Deny always wins.

**How they were used:** in Phases 0–1 the agents defined the boundaries and checklists that the main session followed (for example the security-reviewer checklist was applied on each hook-triggered review). In Phase 2 the same pattern continued: the main session followed the document-intelligence-specialist, security-reviewer and test-engineer checklists while implementing ingestion, parsing, OCR and extraction.

## 4. Agent hooks
Eight hooks live in `.kiro/hooks/` (format `version: v1`):

| Hook | Trigger | Matcher | Action | Validation behavior |
|---|---|---|---|---|
| python-quality | PostFileSave | `backend/**.py` | command: `ruff format` then `ruff check` | Lint errors are returned to the agent. mypy runs in the gate. |
| frontend-quality | PostFileSave | `frontend/src/**.ts(x)` | command: `npm run typecheck` then `npm run lint` | Type and lint errors are returned |
| api-contract | PostFileSave | `backend/app/{schemas,api}/**.py` | command: `scripts/check_openapi.py` | Fails if the generated schema differs from the committed `openapi.json` |
| test-suggestion | PostFileCreate | new `backend/app/{services,api}/**.py` | agent prompt | Asks for unit, property, integration and cross-org tests before the task closes |
| security-review | PostFileSave | security, permissions, signing, db, deps, auth, identity, ingestion, storage | agent prompt | Checklist review against `security.md`, fixing critical and high issues |
| migration-review | PostFileSave | `backend/{app/models,migrations}/**.py` | command: `alembic check` | Fails on model/migration drift (needs Postgres) |
| docs-sync | Stop | none | agent prompt | Lists and updates the docs affected by API, architecture or env changes |
| final-quality-gate | PostTaskExec | none | command: `scripts/quality-gate.ps1` | Full gate after every spec task |

The hooks run only fixed commands. None of them reads `.env` or deletes anything.

## 5. MCP
**Manual setup needed.** Kiro's own permission policy blocks agents from writing `.kiro/settings/`, so the agent did not create this file. Create `.kiro/settings/mcp.json` yourself (command palette → *Kiro: Open workspace MCP config (JSON)*) with:

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest"],
      "disabled": false,
      "autoApprove": ["browser_snapshot", "browser_console_messages", "browser_network_requests"]
    },
    "postgres": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-postgres", "${VERITAS_RO_DATABASE_URL}"],
      "disabled": false,
      "autoApprove": []
    },
    "github": {
      "url": "https://api.githubcopilot.com/mcp/",
      "disabled": true,
      "autoApprove": []
    }
  }
}
```

| Server | Why | Permissions |
|---|---|---|
| playwright | Drive the real UI to check flows and screenshots for the demo | Only read-only snapshot and console tools are auto-approved. Clicks and navigation ask first. |
| postgres | Inspect the schema, RLS policies and the rows the pipeline wrote | Connects as `veritas_readonly` (SELECT only). The URL comes from the `VERITAS_RO_DATABASE_URL` environment variable, never from the file. |
| github | Repo, PRs, CI status for submission | Disabled until you sign in with OAuth |

Rejected: a design-tool server (no Figma file exists) and a filesystem server (Kiro's built-in tools already cover it).

**What MCP enabled:** not used yet, because the config needs the manual step above. In Phases 1 and 2, schema and RLS inspection was done with `psql` in the Postgres container, and UI checks used the Playwright test suite and screenshots instead of the Playwright MCP server.

## 6. Testing and property-based testing
- Hypothesis is mandatory for invariants. The planned and implemented properties are listed per spec. Phase 1 covers password hashing, token round trips, job event ordering and tenant isolation.
- Integration tests run against real Postgres and Redis containers, with RLS tested as the real non-owner `veritas_app` role, not as a superuser.
- **Phase 1 properties (all passing):** Argon2 hash and verify round trip, refresh-hash determinism and distinctness, the job state machine never leaving a terminal state, monotonic capped backoff, URL-safe slugs, rate-limit keys never containing raw emails, gapless increasing persisted event sequences (against real Postgres), and no foreign ids in any read response across random organization and membership sets (against real Postgres).
- **Phase 2 properties (all passing):** formatted amounts round trip through the parser in English and German styles; a currency is never invented when the text has none; grouped integers parse to themselves; unambiguous date formats round trip, and numeric dates such as `03/04/2026` are parsed only when the day and month can't be swapped; name and reference normalization is idempotent; any archive entry name with a `..` segment is unsafe, and plain relative names are safe; identical bytes uploaded several times are stored once per case (against real Postgres and object storage); the deskew inverse transform maps points back to their original page coordinates; line character offsets map back to each source token; a value present in page text is always supported, and a reference absent from it never is (the anti-fabrication check).
- **Phase 3 properties (all passing):**
  - Name normalization is idempotent.
  - Name similarity is symmetric, bounded to 0..1, and 1 for identical names; legal suffixes and letter case don't matter.
  - Amount comparison is order-independent and symmetric.
  - Different currencies never produce a financial finding.
  - A financial finding cites every value of its currency, and its difference equals max − min of the cited values.
  - Dates with different roles never conflict.
  - The relative difference is bounded and order-independent.
  - Evidence confidence is the minimum, and it is null whenever any cited confidence is unmeasured (never invented).
  - Priority never exceeds severity.
- **Bugs PBT caught:** none so far. The Phase 1 defects were caught by integration tests and mypy. The Phase 2 defects were caught by a unit test (deskew on blank pages), an integration test (pagination), the security-review hook (concurrent duplicates), the OCR suites (broken `cv2`) and Playwright (PDF.js worker MIME type). See `docs/implementation-progress.md`.

## 7. Powers
No Kiro Powers were installed for this build so far.

## 8. Examples of Kiro changing the workflow
Recorded from the Phase 0–1 session on 2026-11-23:

- **Steering resolved a design conflict early.** The `security` steering (auto-included when `backend/app/core/db.py` was saved) required `FORCE ROW LEVEL SECURITY`. That would have broken the owner-owned `SECURITY DEFINER` login lookups. Kiro flagged the conflict during the hook-triggered review, and the steering, two specs and the database-architect agent were updated together to the `ENABLE`-only plus non-owner-role design, with a test (`test_app_role_is_not_owner_superuser_or_bypassrls`) that keeps it honest.
- **Hooks ran during development.** The *security-review* hook fired on every save of auth, permission, tenancy and storage code, and each time produced a written checklist review before work continued. The *test-suggestion* hook fired on each new service module. Its test lists became the integration suite (cross-org 404s, the RBAC matrix and the tenant-isolation property).
- **The quality gate blocked false "done" claims.** Before the spec checkboxes were ticked, the gate caught a mypy error introduced by a fix and a formatting drift in a new test. A review of the "Done when" lines also showed two criteria that weren't literally covered: a persisted event-sequence property and an RS256 algorithm-confusion test. Both tests were written before the tasks were ticked.
- **Spec "Done when" lines found real bugs.** Running the specified integration tests against real Postgres (not mocks) exposed that `INSERT … RETURNING` applies RLS SELECT policies. Without that test, failed-login auditing would have 500'd in production.
- **Spec-driven versus vibe:** the RLS, rotation and SSE designs were written in `design.md` first, so implementation was mostly transcription. The bugs that did appear came from environment details (IPv6 `localhost`, a missing Celery extra, an Nginx DNS cache) that the end-to-end smoke test caught.

Recorded from the Phase 2 session on 2026-11-23:

- **The security-review hook found a race.** Saving the ingestion service triggered the review checklist. It pointed out that two concurrent uploads of the same file would both pass the duplicate check and the second would hit the unique constraint as a 500. The fix uses a savepoint and returns `duplicate`, and the dedupe property test covers repeated uploads.
- **The test-suggestion hook shaped the integration suite.** Each new service and router module (cases, ingestion, documents) prompted a test list. Cross-org 404s for every document endpoint and the RLS check across six new tables came from those prompts.
- **The quality gate caught stale and unsafe code.** After the stats card started counting real documents, the gate failed on a Phase 1 assertion that still expected the "pending" state, and on a mypy error in the pipeline runner. Both were fixed before any Phase 2 checkbox was ticked.
- **Tests against real services found bugs that mocks would have hidden.** The case pagination integration test showed page 1 repeating, because a `+` in the ISO timestamp cursor became a space in the query string. Cursors are now opaque base64url and a malformed cursor is a 422. A preprocessing unit test showed deskew rotating blank pages by −5.5°.
- **Steering kept extraction honest.** The `product` hard rules and the `document-processing` steering (loaded on `app/services/extraction/**`) required every value to be verified on its cited page and stored as `null` / `uncertain` otherwise. That led to the `value_is_supported` check and its properties. Because no model credentials were given, the steering also required recording the run as `method=rules` instead of presenting it as AI output.
- **Spec-driven versus vibe:** the stage order in the spec (classify before parse) was wrong, because classification needs text. The spec, design and steering were corrected first, then the code. Environment problems (the archived MinIO images, two OpenCV builds sharing `cv2`, the `.mjs` MIME type) were found by running the real stack, not by the specs.

Recorded from the Phase 3 session on 2026-11-23:

- **The test-suggestion hook set the test list before the code was finished.** It fired on every new module (names, scoring, rules, persistence, findings service, API router). Each prompt listed the public functions and the tests they needed. The resulting tests were:
  - property tests for names and scoring;
  - positive and negative unit cases for every rule;
  - Postgres integration tests for every endpoint, the triggers and the append-only grants;
  - a cross-organization 404 check for all six finding and case endpoints.
- **The security-review hook reviewed the permission change.** Saving `app/core/permissions.py` triggered the checklist. The review confirmed that read-only analysts get `findings:read` only, and that investigators can run comparisons but not decide on findings. It extended the unit test so that the new write permissions are part of the read-only check.
- **Steering shaped the domain wording and the data model.** The `product` hard rules (never declare a document forged, keep three separate values per finding) and the `data-governance` steering (evidence required before confirmation, immutable `ai_output_json`, append-only decisions) became:
  - database triggers;
  - grants without UPDATE or DELETE on decisions and comments;
  - a test that the demo finding's text contains no verdict words;
  - a scan that no `fraud_probability` exists in the code.
  The `ui-design` steering required severity to be shown with a label and an icon, never by color alone.
- **The quality gate caught an environment failure that a single run would have hidden.** A Phase 1 property test failed once with Windows socket exhaustion (`WinError 10055`). Instead of re-running until it passed, the cause was fixed: tests opened a new database connection per session, so they now use the production pool. Two later full runs passed, and the suite got 137 s faster.
- **Spec-driven versus vibe:**
  - Correct from the start: the requirements fixed the acceptance outcome (one USD 20,000 finding, 5 evidence items, no quantity finding), so the rule fixtures and the integration test were written against it.
  - Corrected: the design named migration 0004 and a separate comparison job. The spec was updated to the built design (migration 0003, comparison at the end of every processing job plus an on-demand job).
  - Left open and recorded as not built: the optional LLM interpretation (requirement 6).

Recorded from the live-provider and Phase 4 session on 2026-11-23:

- **Steering decided what "use the model" meant.** The `ai-engineering` steering (a model answer is a claim until it is checked) kept the live Ollama run honest. When `qwen2.5:7b-instruct` returned `68000.00` for a printed `USD 68,000.00`, the claim was rejected and replaced by the verified rules value, not accepted as "close enough". The `testing` steering (live tests marked and reported separately) produced `tests/live` and the `addopts` deselection, so the gate never depends on a running model.
- **The test-suggestion hook ran for every new graph module**: resolution, projection, service, sync, queries and the API router. Each prompt listed the public functions. The resulting tests were:
  - order-independence and evidence properties;
  - real Postgres and Neo4j integration tests;
  - a cross-organization 404 check for all five graph endpoints.
- **The security-review hook reviewed the permission change** (`graph:read`, `graph:rebuild`). The review moved an HTTP `Response` dependency out of the graph service into the router, and confirmed that all Cypher text comes from allowlists with bound values.
- **The quality gate exposed shell state leaking into the run.** One failure came from an environment variable set for the live test in the same shell, not from the code. The variable was cleared and the gate rerun, instead of changing the test.
- **The end-to-end tests caught a real provenance gap.** With the model enabled, two Playwright assertions failed because the viewer labelled fields only "Model provider", hiding whether the value was verified on the text layer or on OCR. The label was fixed, and the tests were kept strict.
- **Spec-driven versus vibe:** the spec's done conditions shaped the tests:
  - "killing Neo4j mid-sync leaves pending rows and recovery applies them" became both an integration test and a real stop-and-start check on the stack (`scripts/graph-outage-check.ps1`);
  - "every edge has evidence" became a database trigger plus a property test.
  The design was corrected where the build differed:
  - migration 0004, not 0006;
  - beat embedded in the worker instead of a new service;
  - a Neo4j namespace, added after reviewing the reconciler showed that tests would otherwise delete the stack's graphs.

Recorded from the Phase 5 (document forensics) session on 2026-11-23:

- **The spec's acceptance conditions forced real calibration.** The task "the recompressed region is flagged and the clean fixture is not" ruled out the first two methods tried: the 8×8 blockiness metric (rendered vector text alone scored z 7.34) and a JPEG ghost. The same happened for stamps. SSIM ranked an altered stamp (0.969) above an honest re-scan (0.936), so the decision metric became `unmatched_ink`. The spec's `design.md` was then rewritten to the built design, and it lists the deviations from the requirements text rather than hiding them.
- **Product steering set the output contract.** The hard rules ("never declares a document authentic or forged") and the spec's mandatory limitation led to these choices:
  - an `Anomaly` type that refuses a severity above medium;
  - a database CHECK with the same cap;
  - an integration test that scans every explanation for verdict words;
  - no path from anomalies to findings, which the module dependency matrix in the `structure` steering also forbids.
- **The security-review hook checked the new permission.** The hook fired when `core/permissions.py` was saved. The review covered three points: `forensics:read` is granted to every role through the read set, both endpoints use `require_permission`, and both filter on `organization_id` with cross-org 404. That gave the RBAC matrix rows and the two-organization isolation test.
- **Spec-driven versus vibe:** the spec placed the forensics stage in parallel with extraction. Building the font check showed it needs the extracted boxes, so the stage runs after `validate`. That was recorded in the design instead of being silently changed.
