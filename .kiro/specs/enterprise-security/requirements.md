# Requirements: Enterprise Security and Governance

## Requirement 1: Tenant isolation
1. Every tenant-owned table SHALL have `organization_id NOT NULL` and RLS enabled with a tenant policy, and the application role SHALL NOT own any table or have `BYPASSRLS`. A schema test SHALL fail if any table with `organization_id` lacks a policy.
2. Storage keys SHALL be prefixed by the organization id, and signed URLs SHALL embed and check the organization.
3. Neo4j and Qdrant queries SHALL always filter by `organization_id`. A test SHALL inspect every query builder for the filter.
4. FOR ANY two organizations, no endpoint SHALL return the other's ids (property test across all GET endpoints).

## Requirement 2: Upload and file safety
1. Malicious upload fixtures (polyglot PDF/ZIP, a ZIP bomb, a path-traversal ZIP, an oversized file, a mismatched extension, an EML with an executable attachment) SHALL be rejected or safely neutralized (attachments are not executed or served).
2. Downloads SHALL set `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`, and a safe filename.

## Requirement 3: API hardening
1. Security headers via Nginx: CSP, HSTS (production), X-Frame-Options DENY, Referrer-Policy and Permissions-Policy.
2. CORS limited to the configured origins.
3. Rate limits on login, upload and investigation start.
4. No SQL built with string formatting (the semgrep rule set passes).

## Requirement 4: Secrets and dependencies
1. A gitleaks scan of the repo SHALL find no secrets.
2. `pip-audit` and `npm audit --audit-level=high` SHALL report no unresolved high or critical vulnerabilities without a documented exception.

## Requirement 5: Retention and audit
1. Organizations can set `retention_days`. A scheduled purge removes expired cases (rows and storage objects) and audits the counts.
2. `audit_logs` cannot be updated or deleted by `veritas_app` (privilege test).

## Requirement 6: Agent security
1. Prompt-injection fixtures SHALL NOT cause tool calls outside the allowlist or status changes.
2. Unauthorized tool calls SHALL be rejected and logged.
