# Security

The rules are in `.kiro/steering/security.md`. This page records what is implemented and verified, and the accepted exceptions. Scanners: `scripts/security-scan.ps1` / `.sh`.

| Control | Implementation | Verified by |
|---|---|---|
| Password storage | Argon2id (argon2-cffi), minimum 12 characters | `tests/unit/test_security.py`, `tests/property/test_invariants.py` |
| User enumeration | Same 401 message for unknown email and wrong password; a dummy hash equalizes timing | `test_auth.py::test_wrong_password_and_unknown_email_give_same_401` |
| Brute force | Redis fixed window per IP and per hashed email; fails closed (503) | `test_auth.py::test_login_rate_limit_returns_429` |
| Expensive actions | Per-member limits on uploads (document and comparison uploads share one budget) and investigation starts; 429 with `Retry-After`; counted only after authentication and permission; fails closed | `tests/integration/security/test_api_hardening.py` |
| Access tokens | HS256 pinned, required claims, 15 min; `alg=none`, tampered signature, wrong secret and wrong type rejected | `tests/unit/test_security.py`, `test_auth.py` |
| Refresh tokens | Opaque and hashed, rotated atomically; reuse revokes the family; logout and member removal revoke | `test_auth.py`, `test_organizations.py` |
| Tenant isolation (database) | Every tenant table: `organization_id` NOT NULL (except unattributed audit rows), indexed, RLS and a policy on `app.current_org`; the app role owns no table and can't bypass RLS. Checked from the catalog, so a new table is covered without a new test. | `tests/integration/security/test_schema_isolation.py`, `test_rls.py` |
| Tenant isolation (API) | Every GET route, read from the OpenAPI schema, answers 404 (or 403 where the role lacks the permission) to another organization for real ids of every resource type; no list leaks an id. A new route fails the test until its parameters are mapped. | `tests/integration/security/test_cross_tenant_reads.py` (Hypothesis over the five roles) |
| Authorization | One permission map, `require_permission` on every route | `test_rbac_matrix.py` (5 roles × every endpoint) |
| Uploads | Magic-byte detection (extension ignored), size limit before full read, ZIP entry/total/ratio/nesting/path checks, a PDF+ZIP polyglot has one interpretation, EML attachments listed but never parsed, stored or served | `tests/integration/security/test_malicious_uploads.py`, `test_ingestion_detect_archive.py` |
| Downloads | Direct opens are `attachment` with a sanitized filename, `nosniff` and a sandbox CSP; the viewer gets an anonymous binary body; report and export links only work on their own endpoints and re-check SHA-256 | `test_malicious_uploads.py`, `test_cases_and_upload.py`, `test_reports.py`, `test_doccompare.py` |
| Storage | Server-generated, org-prefixed keys; originals never overwritten; deletion only by the retention purge and only of a full `{org}/{id}/` prefix | `test_retention.py`, `tests/property/test_security_invariants.py` |
| Retention | `retention_days` drives an hourly purge: storage first, then rows through `purge_expired_case` (tenant- and expiry-checked); one audit entry with counts only; the app role has no DELETE on cases | `test_retention.py`, `test_schema_isolation.py` |
| Audit and trails | `audit_logs`, `job_events`, `agent_events`, `document_versions`, `finding_decisions`, `investigator_comments`, `evidence_requests`, `comparison_reviews`: SELECT and INSERT only | `test_schema_isolation.py::test_trails_are_append_only_for_the_app_role` |
| Agents | Allowlisted read-only tools; unknown or unlisted tools rejected and logged; document text only inside `<document_data>`, and a tag written in a document is escaped so it can't close the block | `test_investigations.py::test_an_injected_document_cannot_trigger_tools_or_change_findings`, `test_security_invariants.py` |
| Errors and logs | problem+json without stack traces (request id only); JSON logs with request, job, task, organization and resource ids; sensitive keys redacted | `test_permissions_and_errors.py`, `test_security_invariants.py` |
| Edge headers | Every Nginx location: CSP (`default-src 'none'` on the API), X-Frame-Options DENY, nosniff, Referrer-Policy, Permissions-Policy; HSTS only behind TLS (`X-Forwarded-Proto: https`); server version hidden | `frontend/tests/e2e/security-headers.spec.ts` |
| CORS | Only the configured origins; no credentials; only the API's methods | `test_api_hardening.py`, `security-headers.spec.ts` |
| Login redirect | Only same-app paths after sign-in (`//host`, `/\host`, control characters refused) | `frontend/src/features/auth/redirect.test.ts` |
| SQL | ORM or bound parameters; the semgrep rule `veritas-sql-string-formatting` fails on string-built SQL | `scripts/security-scan.ps1` |
| Secrets and dependencies | Environment only, `.env` ignored; gitleaks, pip-audit, npm audit (high and critical), semgrep, bandit | `scripts/security-scan.ps1` |

## Accepted exceptions
| Finding | Severity | Why accepted | Revisit |
|---|---|---|---|
| react-router 6 GHSA-wrjc-x8rr-h8h6 (open redirect via backslash paths) | moderate | The only navigation target built from a URL is the post-login return path, now guarded by `safeReturnPath`; other targets are app ids | Upgrade to react-router 7 |
| react-router 6 GHSA-337j-9hxr-rhxg (SSR `deserializeErrors`) | moderate | Server-side rendering and hydration aren't used (static SPA) | Same upgrade |
| `@vitest/mocker` advisory | moderate | Test runner only; not in the image | vitest 4 |
| Migration DDL with formatted identifiers (8 lines, annotated `nosemgrep`) | n/a | Identifiers can't be bound; each passes `_ident` or a strict regex, or comes from a constant list | — |

## Known limitations
- **Refresh token in localStorage (medium).** An XSS bug could steal it. Mitigations: strict CSP without inline scripts, rotation and reuse detection. An httpOnly cookie is not built.
- **Concurrent refresh from two tabs (low).** Treated as reuse; both tabs are signed out.
- **Member lookup by email (low).** Admins adding a member learn whether an email is registered.
- **TLS** terminates at the deployment edge; this repository sets HSTS only when that edge reports HTTPS.
- **One worker slot.** Short tasks can wait behind document processing (measured in the progress doc).
