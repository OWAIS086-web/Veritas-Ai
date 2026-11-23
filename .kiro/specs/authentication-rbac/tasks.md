# Tasks: Authentication and RBAC

- [x] 1. Security primitives
  - `app/core/security.py`, `app/core/permissions.py`
  - Done when: the unit tests for hashing, tokens (expiry, tamper, alg confusion) and permission-map completeness pass, plus the Hypothesis hashing property.
  - _Requirements: 1.4, 3.1, 3.2_

- [x] 2. Registration and login with rate limiting and audit
  - `app/services/identity/auth.py`, `rate_limit.py`, `app/services/audit/service.py`, `app/api/v1/auth.py`, the SECURITY DEFINER functions in migration 0001
  - Done when: the register, login, wrong-password, duplicate-email, short-password and 429 integration tests pass, and the audit rows exist.
  - _Requirements: 1.1–1.5, 2.1–2.4_

- [x] 3. Refresh rotation, reuse detection, logout, /me
  - Done when: rotation issues a new pair, reusing the old token revokes the family (the new token fails too), logout revokes, and `/me` returns the permissions.
  - _Requirements: 3.3–3.6, 4.1_

- [x] 4. Organizations and members
  - `app/services/identity/organizations.py`, `members.py`, `app/api/v1/organizations.py`
  - Done when: the list, create, get and patch tests pass, cross-org returns 404, an insufficient role returns 403, and demoting the last admin returns 409.
  - _Requirements: 5.1–5.5, 6.1–6.4_

- [x] 5. Audit log API
  - Done when: the paginated listing works, the cursor is stable, and another org's entries are never returned.
  - _Requirements: 7.1–7.2_

- [x] 6. RBAC matrix and tenant-isolation property tests
  - Done when: the parametrized role × endpoint test and the Hypothesis isolation property pass against real Postgres.
  - _Requirements: 6.3, 8.1_

- [x] 7. Frontend auth and organization screens
  - Login, Register, protected routes, the Settings > Organization and members page, and the Audit Logs page
  - Done when: the Vitest UI-state tests and the Playwright flow (register → login → overview → audit log) pass.
  - _Requirements: 1.1, 2.1, 5.1, 6.1, 7.1_
