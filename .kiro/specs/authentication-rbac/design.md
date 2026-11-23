# Design: Authentication and RBAC

## Components
| Component | File | Responsibility |
|---|---|---|
| Password hashing | `app/core/security.py` | `hash_password`, `verify_password`, `needs_rehash` (argon2-cffi `PasswordHasher`) |
| Tokens | `app/core/security.py` | `create_access_token`, `decode_access_token` (PyJWT, `algorithms=["HS256"]`, requires `exp`, `sub`, `type`), `new_refresh_token()` (32 random bytes, urlsafe), `hash_refresh_token` (SHA-256) |
| Permission map | `app/core/permissions.py` | `ROLE_PERMISSIONS: dict[Role, frozenset[str]]` |
| Auth dependencies | `app/api/deps.py` | `get_principal` (decodes the token, loads the membership, sets the tenant), `require_permission(p)`, `get_tenant_session` |
| Identity service | `app/services/identity/{auth,organizations,members}.py` | Business logic |
| Rate limiter | `app/services/identity/rate_limit.py` | Redis fixed window, `INCR` plus `EXPIRE`, keys `rl:login:ip:{ip}` and `rl:login:email:{sha256(email)}` |
| Audit | `app/services/audit/service.py` | `record(session, action, ...)`, `list_for_org(...)` |

## Permission map
| Permission | org_admin | investigation_manager | investigator | reviewer | read_only_analyst |
|---|---|---|---|---|---|
| org:read | ● | ● | ● | ● | ● |
| org:update | ● | | | | |
| members:read | ● | ● | ● | ● | ● |
| members:manage | ● | | | | |
| audit:read | ● | ● | | | |
| stats:read | ● | ● | ● | ● | ● |
| jobs:read | ● | ● | ● | ● | ● |
| system:ping | ● | ● | | | |
| cases:read | ● | ● | ● | ● | ● |
| cases:write | ● | ● | ● | | |
| cases:delete | ● | ● | | | |
| documents:read | ● | ● | ● | ● | ● |
| documents:upload | ● | ● | ● | | |
| documents:process | ● | ● | ● | | |
| findings:review | ● | ● | | ● | |

## Sequence: login
1. Rate-limit check on IP and email. Exceeded returns 429.
2. `auth_lookup_user(email)`, a SECURITY DEFINER function. If no row is found, the service still verifies the password against a dummy hash so timing is the same, then returns 401.
3. Verify the password. On failure, audit `auth.login_failed` (org null) and return 401.
4. Pick the membership with `auth_memberships(user_id)`. With no membership, return 401.
5. Open a tenant session for the org, insert a refresh token (new family), audit `auth.login`, commit, and return the pair.

## Sequence: refresh
1. Hash the presented token and call `auth_find_refresh(hash)`. If no row is found, return 401.
2. If `revoked_at` is set (reuse), revoke the whole family (in the tenant session for that token's org), audit `auth.refresh_reuse`, and return 401.
3. If expired, return 401.
4. Check the membership still exists, revoke the current token, insert a new one with the same family and `replaced_by_id`, and issue an access token.

## Tenant context
`get_principal` decodes the JWT and opens a transaction with `SET LOCAL app.current_org = :org` (via `set_config('app.current_org', :org, true)`, which takes a bound parameter). It loads the membership `(org, user)` under RLS. A missing membership returns 401. The same session is yielded to the handler, so every query runs under RLS.

## API schemas
- `RegisterRequest{email: EmailStr, password: str(min 12, max 128), full_name: str(1..200), organization_name: str(2..200)}`
- `LoginRequest{email, password, organization_id?: UUID}`
- `TokenPair{access_token, refresh_token, token_type, expires_in}`
- `MeResponse{user: UserOut, organization: OrganizationOut, role: RoleKey, permissions: list[str]}`
- `OrganizationOut{id, name, slug, retention_days, created_at}`, `OrganizationCreate{name}`, `OrganizationUpdate{name?, retention_days? (1..3650 | null)}`
- `MemberOut{user_id, email, full_name, role, created_at}`, `MemberAdd{email, role}`, `MemberRoleUpdate{role}`
- `AuditLogOut{id, action, resource_type, resource_id, actor_user_id, ip, created_at, metadata}`
- `Page[T]{items: list[T], next_cursor: str | None}`

## Failure handling
- Redis is unavailable during login: return 503 (fail closed) and log it.
- A unique-constraint race on register: catch the `IntegrityError` and return 409.
- An access token whose `org` membership was removed: return 401 at the dependency.

## Testing
- Unit: hashing round trip; token create, decode, expire and tamper; the `alg=none` and RS256 confusion cases are rejected; the permission map is complete for all roles.
- Integration: every endpoint's happy and failure paths; refresh rotation and reuse revocation; the 429 case; the role-by-endpoint matrix (parametrized); cross-org 404s.
- Property (Hypothesis): `verify_password(p, hash_password(p))` holds and a different password fails; random org and member graphs never return the other org's ids.
