# Security (Phase 1 state)

The rules are in `.kiro/steering/security.md`. This page records what is implemented and verified.

| Control | Implementation | Verified by |
|---|---|---|
| Password storage | Argon2id (argon2-cffi), minimum 12 characters | `tests/unit/test_security.py`, `tests/property/test_invariants.py` |
| User enumeration | Same 401 message for unknown email and wrong password. A dummy hash equalizes timing. | `test_auth.py::test_wrong_password_and_unknown_email_give_same_401` |
| Brute force | Redis fixed window per IP and per hashed email. Fails closed (503) if Redis is down. | `test_auth.py::test_login_rate_limit_returns_429` |
| Access tokens | HS256 pinned, required claims, 15 min. `alg=none`, a tampered signature, a wrong secret and a wrong type are all rejected. | `tests/unit/test_security.py`, `test_auth.py::test_bad_tokens_are_401` |
| Refresh tokens | Opaque and hashed, rotated atomically. Reuse revokes the family. Logout revokes. Member removal revokes. | `test_auth.py`, `test_organizations.py` |
| Revocation latency | Every request re-checks the membership, so removal takes effect immediately | `test_members_add_change_remove_and_last_admin_guard` |
| Tenant isolation | RLS on every tenant table, explicit organization filters, 404 across tenants | `test_rls.py`, `test_tenant_isolation_property.py` (Hypothesis), `test_organizations.py` |
| Authorization | One permission map, `require_permission` on every route | `test_rbac_matrix.py` (5 roles × 7 endpoints) |
| Audit | Append-only (no UPDATE or DELETE grant). Login, failure, refresh reuse, logout, organization and member changes. | `test_rls.py::test_audit_log_is_append_only_for_app_role` |
| Errors | problem+json, no stack traces | `tests/unit/test_permissions_and_errors.py` |
| Logs | JSON, sensitive keys redacted | `test_log_formatter_redacts_sensitive_fields` |
| Headers | CSP, X-Frame-Options DENY, nosniff, Referrer-Policy, Permissions-Policy (Nginx) | `scripts/smoke.ps1` checks the CSP |
| Proxy IP spoofing | Nginx overwrites `X-Forwarded-For` with the peer address | config review |
| Secrets | Only from the environment. `.env` is git-ignored. Gitleaks scan clean. | gitleaks run, 2026-11-23 |

## Known limitations and accepted risks
- **Refresh token in localStorage (medium).** An XSS bug could steal it. Mitigations: a strict CSP with no inline scripts, rotation, and reuse detection. Planned hardening: an httpOnly SameSite cookie (enterprise-security spec).
- **Concurrent refresh from two tabs (low).** Treated as reuse and signs both out. This is intended strict behavior.
- **Member lookup by email (low).** Admins adding a member learn whether an email is registered.
- **HSTS and TLS** are expected at the deployment edge and aren't configured in this repo.
- Dependency vulnerability scans (`pip-audit`, `npm audit`) and semgrep are scheduled for the security phase.
