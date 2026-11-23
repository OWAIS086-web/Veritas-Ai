# Requirements: Authentication and RBAC

## Introduction
User registration, login, token lifecycle, organizations, memberships, role-based permissions and the audit trail for identity events.

## Requirement 1: Registration
**User story:** As a new customer, I want to register and get my own organization so I can start investigations.

Acceptance criteria:
1. WHEN `POST /auth/register` receives a valid `{email, password, full_name, organization_name}` THE SYSTEM SHALL create the user, a new organization, and an `org_admin` membership in one transaction, and return 201 with tokens.
2. WHEN the password is shorter than 12 characters THE SYSTEM SHALL return 422.
3. WHEN the email already exists THE SYSTEM SHALL return 409 with a generic message.
4. THE SYSTEM SHALL store the password only as an Argon2id hash.
5. THE SYSTEM SHALL write an `auth.register` audit entry.

## Requirement 2: Login
Acceptance criteria:
1. WHEN `POST /auth/login` receives correct credentials THE SYSTEM SHALL return 200 with `{access_token, refresh_token, token_type:"bearer", expires_in}`.
2. WHEN the credentials are wrong or the user is inactive THE SYSTEM SHALL return 401 with the same generic message in both cases, and write an `auth.login_failed` audit entry.
3. WHEN more than `VERITAS_LOGIN_RATE_LIMIT_PER_MINUTE` attempts come from one IP or for one email within 60 s THE SYSTEM SHALL return 429 with `Retry-After`.
4. WHEN a user belongs to several organizations THE SYSTEM SHALL accept an optional `organization_id` and SHALL default to the earliest membership.

## Requirement 3: Tokens
Acceptance criteria:
1. THE SYSTEM SHALL issue access tokens as HS256 JWTs with `sub, org, role, type=access, jti, iat, exp`, valid for `VERITAS_ACCESS_TOKEN_MINUTES`.
2. WHEN a request carries an expired, tampered, wrong-type or wrong-algorithm token THE SYSTEM SHALL return 401.
3. WHEN `POST /auth/refresh` receives a valid refresh token THE SYSTEM SHALL revoke it, issue a new pair in the same family, and return 200.
4. WHEN an already-rotated refresh token is presented THE SYSTEM SHALL revoke every token in its family and return 401.
5. WHEN `POST /auth/logout` is called with a refresh token THE SYSTEM SHALL revoke its family and return 204.
6. WHEN the user's membership was removed THE SYSTEM SHALL reject access and refresh tokens for that organization.

## Requirement 4: Current user
1. WHEN `GET /auth/me` is called with a valid token THE SYSTEM SHALL return `{user, organization, role, permissions}`.

## Requirement 5: Organizations
Acceptance criteria:
1. WHEN `GET /organizations` is called THE SYSTEM SHALL return only the organizations the caller is a member of.
2. WHEN `POST /organizations` is called by an authenticated user THE SYSTEM SHALL create an organization with the caller as `org_admin`.
3. WHEN `GET /organizations/{id}` or `PATCH /organizations/{id}` targets an organization the caller is not a member of THE SYSTEM SHALL return 404.
4. WHEN `PATCH` is called by a role without `org:update` THE SYSTEM SHALL return 403.
5. THE SYSTEM SHALL audit organization creation and updates.

## Requirement 6: Members and roles
Acceptance criteria:
1. WHEN an `org_admin` calls `POST /organizations/{id}/members` with an existing user's email and a role THE SYSTEM SHALL add the membership.
2. WHEN an `org_admin` calls `PATCH /organizations/{id}/members/{user_id}` THE SYSTEM SHALL change the role, and SHALL refuse (409) to demote the last `org_admin`.
3. THE SYSTEM SHALL enforce the permission map in `app/core/permissions.py` for every protected endpoint, and SHALL return 403 for an insufficient role inside the caller's own organization.
4. THE SYSTEM SHALL audit membership and role changes.

## Requirement 7: Audit log access
1. WHEN `GET /audit-logs` is called by a role with `audit:read` THE SYSTEM SHALL return the caller's organization's entries, newest first, with cursor pagination (`limit` ≤ 100).
2. THE SYSTEM SHALL NOT return entries of other organizations.

## Requirement 8: Tenant isolation (property)
1. FOR ANY two organizations A and B with arbitrary members, THE SYSTEM SHALL NOT return any id belonging to B in any response to a user of A.
