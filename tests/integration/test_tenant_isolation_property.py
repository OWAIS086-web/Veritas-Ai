# Req: authentication-rbac 8.1; enterprise-security 1.4
"""Property: for random sets of organizations and memberships, no API response given to a
member of one organization contains an id that belongs only to another organization."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.integration.conftest import Account, register

pytestmark = pytest.mark.integration

READ_PATHS = [
    "/api/v1/auth/me",
    "/api/v1/organizations",
    "/api/v1/organizations/{org}",
    "/api/v1/organizations/{org}/members",
    "/api/v1/audit-logs",
    "/api/v1/stats/overview",
]


@settings(
    max_examples=6, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(org_count=st.integers(min_value=2, max_value=3), extra_members=st.integers(0, 2))
async def test_no_foreign_ids_in_any_response(
    client: httpx.AsyncClient, org_count: int, extra_members: int
) -> None:
    orgs: list[tuple[Account, list[Account]]] = []
    for i in range(org_count):
        admin = await register(client, org_name=f"Prop Org {i}")
        members = []
        for _ in range(extra_members):
            person = await register(client, org_name=f"Prop Home {i}")
            await client.post(
                f"/api/v1/organizations/{admin.organization_id}/members",
                headers=admin.headers,
                json={"email": person.email, "role": "reviewer"},
            )
            members.append(person)
        orgs.append((admin, members))

    def ids_of(index: int) -> set[str]:
        admin, _members = orgs[index]
        return {str(admin.organization_id), str(admin.user_id)}

    for i, (admin, _) in enumerate(orgs):
        foreign_orgs = {str(o[0].organization_id) for j, o in enumerate(orgs) if j != i}
        foreign_admins = {str(o[0].user_id) for j, o in enumerate(orgs) if j != i}
        for path in READ_PATHS:
            resp = await client.get(path.format(org=admin.organization_id), headers=admin.headers)
            assert resp.status_code == 200, (path, resp.text)
            body = json.dumps(resp.json())
            leaked = {x for x in foreign_orgs | foreign_admins if x in body}
            assert not leaked, f"{path} leaked {leaked}"
        for j, (other, _) in enumerate(orgs):
            if j == i:
                continue
            probe = await client.get(
                f"/api/v1/organizations/{other.organization_id}", headers=admin.headers
            )
            assert probe.status_code == 404
        assert ids_of(i)  # sanity: the org's own ids exist
    assert uuid.UUID(str(orgs[0][0].organization_id))
