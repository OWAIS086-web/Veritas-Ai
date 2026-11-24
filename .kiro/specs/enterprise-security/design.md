# Design: Enterprise Security

## Controls by layer
| Layer | Control | Where |
|---|---|---|
| Edge | TLS (production), security headers, request size limit, proxy rate limiting | `infrastructure/nginx/nginx.conf`, `docker-compose.prod.yml` |
| API | JWT auth, permission map, Pydantic validation, problem+json, Redis rate limits | `app/api/deps.py`, `app/core/permissions.py` |
| Service | Explicit org filters, evidence rules | services |
| Database | RLS forced, non-owner app role, SECURITY DEFINER auth functions, audit table INSERT and SELECT only | migrations |
| Storage | Server-generated, org-prefixed keys, HMAC signed URLs, `put_new` (no overwrite) | `app/integrations/storage`, `app/core/signing.py` |
| Agents | Tool allowlist gateway, reference validator, delimited data, budgets | `app/agents` |
| Supply chain | pip-audit, npm audit, gitleaks, pinned lockfiles (`uv.lock`, `package-lock.json`) | `scripts/security-scan.ps1` |

## Schema-level isolation test
The test queries `pg_class` and `pg_policy` for every table with an `organization_id` column, and asserts `relrowsecurity` and at least one policy. It also asserts that `veritas_app` owns no table and has neither `rolbypassrls` nor `rolsuper`. RLS is deliberately not forced; see `security.md`.

## Threat model summary (STRIDE)
- **Spoofing:** short JWTs, refresh rotation and reuse detection.
- **Tampering:** immutable originals, an append-only audit log, and the immutable `ai_output_json`.
- **Repudiation:** audit of every sensitive action.
- **Information disclosure:** RLS, 404 across tenants, and signed URLs.
- **Denial of service:** size, ZIP and page limits, rate limits, and task time limits.
- **Elevation of privilege:** the permission map and agents with no write tools.

## Testing
Security tests live in `backend/tests/integration/security/` (they need the integration database fixtures) and run in the default suite. Pure security invariants are in `backend/tests/property/test_security_invariants.py`. The scanners run in `scripts/security-scan.ps1` and `.sh`.
