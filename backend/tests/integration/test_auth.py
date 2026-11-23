# Req: authentication-rbac 1.x, 2.x, 3.x, 4.1
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.core.db import session_scope
from app.models import AuditLog, User
from tests.integration.conftest import TEST_RATE_LIMIT, login, register, unique_email

pytestmark = pytest.mark.integration


async def test_register_creates_user_org_admin_and_tokens(client: httpx.AsyncClient) -> None:
    acct = await register(client, org_name="Northwind Trading")
    me = (await client.get("/api/v1/auth/me", headers=acct.headers)).json()
    assert me["role"] == "org_admin"
    assert me["organization"]["name"] == "Northwind Trading"
    assert "members:manage" in me["permissions"]
    async with session_scope() as s:
        user = await s.scalar(select(User).where(User.email == acct.email))
        assert user is not None
        assert user.password_hash.startswith("$argon2id$")
        assert acct.password not in user.password_hash


async def test_register_duplicate_email_is_conflict(client: httpx.AsyncClient) -> None:
    email = unique_email()
    await register(client, email=email)
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email.upper(),
            "password": "another-password-123",
            "full_name": "X",
            "organization_name": "Other Org",
        },
    )
    assert resp.status_code == 409
    assert resp.headers["content-type"].startswith("application/problem+json")


async def test_register_short_password_is_422(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": unique_email(),
            "password": "short",
            "full_name": "X",
            "organization_name": "Org",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["errors"]


async def test_login_success_and_audit(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    again = await login(client, acct)
    assert (await client.get("/api/v1/auth/me", headers=again.headers)).status_code == 200
    logs = (await client.get("/api/v1/audit-logs", headers=again.headers)).json()["items"]
    actions = [entry["action"] for entry in logs]
    assert "auth.login" in actions and "auth.register" in actions


async def test_wrong_password_and_unknown_email_give_same_401(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    wrong = await client.post(
        "/api/v1/auth/login", json={"email": acct.email, "password": "not-the-password"}
    )
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": unique_email(), "password": "whatever-123456"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


async def test_failed_login_is_audited_in_the_org(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    await client.post("/api/v1/auth/login", json={"email": acct.email, "password": "bad-pw-1234"})
    logs = (await client.get("/api/v1/audit-logs", headers=acct.headers)).json()["items"]
    assert any(e["action"] == "auth.login_failed" for e in logs)


async def test_login_rate_limit_returns_429(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    codes = []
    for _ in range(TEST_RATE_LIMIT + 2):
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": acct.email, "password": "wrong-pass-123"},  # gitleaks:allow (test value)
        )
        codes.append(r.status_code)
    assert codes[:TEST_RATE_LIMIT] == [401] * TEST_RATE_LIMIT
    assert codes[-1] == 429
    last = await client.post(
        "/api/v1/auth/login", json={"email": acct.email, "password": acct.password}
    )
    assert last.status_code == 429
    assert int(last.headers["Retry-After"]) >= 1


@pytest.mark.parametrize(
    "header",
    [
        "Bearer not-a-jwt",
        "Bearer eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJ4In0.",
        "Basic dXNlcjpwYXNz",
    ],
)
async def test_bad_tokens_are_401(client: httpx.AsyncClient, header: str) -> None:
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": header})
    assert resp.status_code == 401


async def test_missing_token_is_401(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_refresh_rotates_and_old_token_reuse_revokes_family(
    client: httpx.AsyncClient,
) -> None:
    acct = await register(client)
    first = await client.post("/api/v1/auth/refresh", json={"refresh_token": acct.refresh})
    assert first.status_code == 200
    new_refresh = first.json()["refresh_token"]
    assert new_refresh != acct.refresh

    reuse = await client.post("/api/v1/auth/refresh", json={"refresh_token": acct.refresh})
    assert reuse.status_code == 401
    # The reuse revoked the whole family, including the newest token.
    after = await client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert after.status_code == 401
    logs = (await client.get("/api/v1/audit-logs", headers=acct.headers)).json()["items"]
    assert any(e["action"] == "auth.refresh_reuse_detected" for e in logs)


async def test_logout_revokes_refresh(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    out = await client.post("/api/v1/auth/logout", json={"refresh_token": acct.refresh})
    assert out.status_code == 204
    again = await client.post("/api/v1/auth/refresh", json={"refresh_token": acct.refresh})
    assert again.status_code == 401


async def test_logout_with_unknown_token_is_still_204(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/logout", json={"refresh_token": "x" * 43})
    assert resp.status_code == 204


async def test_audit_rows_never_contain_secrets(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    await client.post("/api/v1/auth/refresh", json={"refresh_token": acct.refresh})
    async with session_scope() as s:
        from app.core.db import set_tenant

        await set_tenant(s, acct.organization_id)
        rows = (await s.scalars(select(AuditLog))).all()
    blob = " ".join(str(r.metadata_) for r in rows)
    assert acct.password not in blob and acct.refresh not in blob
