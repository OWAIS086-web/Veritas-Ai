# Req: authentication-rbac 5.x, 6.x, 7.x
from __future__ import annotations

import httpx
import pytest

from tests.integration.conftest import login, register

pytestmark = pytest.mark.integration


async def test_list_and_get_own_organization(client: httpx.AsyncClient) -> None:
    acct = await register(client, org_name="Blue Harbor")
    orgs = (await client.get("/api/v1/organizations", headers=acct.headers)).json()
    assert [o["name"] for o in orgs] == ["Blue Harbor"]
    one = await client.get(f"/api/v1/organizations/{acct.organization_id}", headers=acct.headers)
    assert one.status_code == 200


async def test_other_org_is_404_for_get_and_patch(client: httpx.AsyncClient) -> None:
    a = await register(client, org_name="Org A")
    b = await register(client, org_name="Org B")
    for resp in (
        await client.get(f"/api/v1/organizations/{b.organization_id}", headers=a.headers),
        await client.patch(
            f"/api/v1/organizations/{b.organization_id}",
            headers=a.headers,
            json={"name": "Hijacked"},
        ),
        await client.get(f"/api/v1/organizations/{b.organization_id}/members", headers=a.headers),
    ):
        assert resp.status_code == 404
    still = (
        await client.get(f"/api/v1/organizations/{b.organization_id}", headers=b.headers)
    ).json()
    assert still["name"] == "Org B"


async def test_patch_updates_and_audits(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    resp = await client.patch(
        f"/api/v1/organizations/{acct.organization_id}",
        headers=acct.headers,
        json={"name": "Renamed Ltd", "retention_days": 365},
    )
    assert resp.status_code == 200
    assert resp.json()["retention_days"] == 365
    logs = (await client.get("/api/v1/audit-logs", headers=acct.headers)).json()["items"]
    update = next(e for e in logs if e["action"] == "organization.update")
    assert update["metadata"]["fields"] == ["name", "retention_days"]


async def test_create_second_org_and_login_into_it(client: httpx.AsyncClient) -> None:
    acct = await register(client, org_name="First")
    created = await client.post(
        "/api/v1/organizations", headers=acct.headers, json={"name": "Second"}
    )
    assert created.status_code == 201
    second_id = created.json()["id"]
    orgs = (await client.get("/api/v1/organizations", headers=acct.headers)).json()
    assert {o["name"] for o in orgs} == {"First", "Second"}
    # The current token is scoped to "First": "Second" is not visible through it.
    hidden = await client.get(f"/api/v1/organizations/{second_id}", headers=acct.headers)
    assert hidden.status_code == 404
    switched = await login(client, acct, organization_id=created.json()["id"])
    visible = await client.get(f"/api/v1/organizations/{second_id}", headers=switched.headers)
    assert visible.status_code == 200


async def test_members_add_change_remove_and_last_admin_guard(
    client: httpx.AsyncClient,
) -> None:
    admin = await register(client, org_name="Team Org")
    other = await register(client, org_name="Their Own Org")
    base = f"/api/v1/organizations/{admin.organization_id}/members"

    added = await client.post(
        base, headers=admin.headers, json={"email": other.email, "role": "investigator"}
    )
    assert added.status_code == 201
    dup = await client.post(
        base, headers=admin.headers, json={"email": other.email, "role": "reviewer"}
    )
    assert dup.status_code == 409
    missing = await client.post(
        base, headers=admin.headers, json={"email": "nobody@example.com", "role": "reviewer"}
    )
    assert missing.status_code == 404

    changed = await client.patch(
        f"{base}/{other.user_id}", headers=admin.headers, json={"role": "reviewer"}
    )
    assert changed.json()["role"] == "reviewer"

    demote_self = await client.patch(
        f"{base}/{admin.user_id}", headers=admin.headers, json={"role": "investigator"}
    )
    assert demote_self.status_code == 409

    member_session = await login(client, other, organization_id=admin.organization_id)
    assert (await client.get("/api/v1/auth/me", headers=member_session.headers)).json()[
        "role"
    ] == "reviewer"

    removed = await client.delete(f"{base}/{other.user_id}", headers=admin.headers)
    assert removed.status_code == 204
    # Removal takes effect immediately for the access token and the refresh token.
    assert (await client.get("/api/v1/auth/me", headers=member_session.headers)).status_code == 401
    refresh = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": member_session.refresh}
    )
    assert refresh.status_code == 401

    actions = [
        e["action"]
        for e in (await client.get("/api/v1/audit-logs", headers=admin.headers)).json()["items"]
    ]
    assert {"member.add", "member.role_change", "member.remove"} <= set(actions)


async def test_audit_pagination(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    for i in range(4):
        await client.patch(
            f"/api/v1/organizations/{acct.organization_id}",
            headers=acct.headers,
            json={"name": f"Name {i}"},
        )
    page1 = (await client.get("/api/v1/audit-logs?limit=2", headers=acct.headers)).json()
    assert len(page1["items"]) == 2 and page1["next_cursor"]
    page2 = (
        await client.get(
            f"/api/v1/audit-logs?limit=2&cursor={page1['next_cursor']}", headers=acct.headers
        )
    ).json()
    ids1 = {e["id"] for e in page1["items"]}
    ids2 = {e["id"] for e in page2["items"]}
    assert ids1.isdisjoint(ids2)
    assert max(ids2) < min(ids1)
    too_big = await client.get("/api/v1/audit-logs?limit=500", headers=acct.headers)
    assert too_big.status_code == 422
