# Req: enterprise-security 1.4
"""Property: for any member of another organization, whatever their role, every GET endpoint
of the API answers 404 for this organization's real ids, and no list it can read contains
them.

The routes come from the OpenAPI schema, so a new GET endpoint is covered automatically, and
the test fails until each of its path parameters is mapped to a real id below. One
organization is given real data behind every endpoint: a processed invoice and customs
declaration (findings, evidence, graph), an investigation, a report and a document
comparison with its findings and exports."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select

from app.core.db import tenant_session
from app.core.permissions import Role
from app.integrations.storage.s3_store import get_store
from app.models import (
    ComparisonExport,
    ComparisonFinding,
    Entity,
    Finding,
    Relationship,
)
from app.services.doccompare.run import generate_export, queued_exports, run_comparison
from app.services.doccompare.vision import Vision
from app.services.investigations.run import run_investigation
from app.services.reporting import service as report_service
from tests.agent_provider import ScriptedProvider
from tests.integration.conftest import Account, login, register
from tests.integration.test_findings import _process

pytestmark = pytest.mark.integration

# Served through a signed link (the token carries the organization), not a bearer token.
SIGNED = {"token"}
# Streams: the outsider's 404 is checked; the owner's sanity check skips the stream.
STREAMS = re.compile(r"/events$")
PARAM = re.compile(r"\{([a-z_]+)\}")


@dataclass
class Owned:
    acct: Account
    ids: dict[str, str]  # path parameter → a real id of this organization
    all_ids: set[str]


async def _no_vision() -> tuple[Vision | None, str, str | None]:
    return None, "disabled", "not used in this test"


async def _owned(c: httpx.AsyncClient) -> Owned:
    p = await _process(c, ["02_commercial_invoice.pdf", "03_customs_declaration.pdf"])
    org, h = p.acct.organization_id, p.acct.headers
    docs = (await c.get(f"/api/v1/cases/{p.case_id}/documents", headers=h)).json()
    inv = await c.post(
        f"/api/v1/cases/{p.case_id}/investigate", headers=h, json={"objective": "Check values"}
    )
    assert inv.status_code == 202, inv.text
    inv_id = inv.json()["id"]
    assert await run_investigation(org, uuid.UUID(inv_id), ScriptedProvider()) == "awaiting_review"
    rep = await c.post(f"/api/v1/cases/{p.case_id}/reports", headers=h, json={"format": "json"})
    assert rep.status_code == 202, rep.text
    assert await report_service.generate(org, uuid.UUID(rep.json()["id"]), get_store()) == (
        "completed"
    )
    cmp = await c.post(
        f"/api/v1/cases/{p.case_id}/comparisons",
        headers=h,
        json={"original_document_id": docs[0]["id"], "test_document_id": docs[1]["id"]},
    )
    assert cmp.status_code == 202, cmp.text
    cmp_id = cmp.json()["id"]
    assert await run_comparison(org, uuid.UUID(cmp_id), get_store(), _no_vision) == "completed"
    for eid in await queued_exports(org, uuid.UUID(cmp_id)):
        await generate_export(org, eid, get_store())
    async with tenant_session(org) as s:
        finding = await s.scalar(select(Finding.id).where(Finding.organization_id == org))
        entity = await s.scalar(select(Entity.id).where(Entity.organization_id == org))
        relationship = await s.scalar(
            select(Relationship.id).where(Relationship.organization_id == org)
        )
        cmp_finding = await s.scalar(
            select(ComparisonFinding.id).where(ComparisonFinding.organization_id == org)
        )
        export = await s.scalar(
            select(ComparisonExport.id).where(ComparisonExport.organization_id == org)
        )
    for name, value in (
        ("finding", finding),
        ("entity", entity),
        ("relationship", relationship),
        ("comparison finding", cmp_finding),
        ("export", export),
    ):
        assert value is not None, f"the fixture has no {name}"
    ids = {
        "organization_id": str(org),
        "case_id": p.case_id,
        "job_id": p.job_id,
        "document_id": docs[0]["id"],
        "finding_id": str(finding),
        "entity_id": str(entity),
        "relationship_id": str(relationship),
        "investigation_id": inv_id,
        "report_id": rep.json()["id"],
        "comparison_id": cmp_id,
        "export_id": str(export),
    }
    all_ids = {*ids.values(), str(cmp_finding), *(d["id"] for d in docs), str(p.acct.user_id)}
    return Owned(p.acct, ids, all_ids)


def _fill(path: str, ids: dict[str, str], cmp_finding: str) -> str:
    if "/comparisons/{comparison_id}/findings/{finding_id}" in path:
        # On comparison routes, finding_id is a comparison finding.
        path = path.replace("{finding_id}", cmp_finding)
    return PARAM.sub(lambda m: ids[m.group(1)], path)


@dataclass
class Fixture:
    owned: Owned
    cmp_finding: str
    routes: list[str]


@pytest.fixture(scope="module")
async def world(app: Any) -> AsyncIterator[Fixture]:
    transport = httpx.ASGITransport(app=app, client=("10.9.8.1", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        owned = await _owned(c)
        async with tenant_session(owned.acct.organization_id) as s:
            cmp_finding = str(await s.scalar(select(ComparisonFinding.id)))
        paths = app.openapi()["paths"]
        routes = sorted(p for p, ops in paths.items() if "get" in ops and p.startswith("/api/v1"))
        yield Fixture(owned, cmp_finding, routes)


async def test_every_get_route_parameter_is_mapped(world: Fixture) -> None:
    params = {m for r in world.routes for m in PARAM.findall(r)}
    unmapped = params - set(world.owned.ids) - SIGNED
    assert not unmapped, f"map these path parameters to a real id: {sorted(unmapped)}"
    assert len(world.routes) >= 40


async def test_the_owner_reaches_every_route_with_these_ids(
    client: httpx.AsyncClient, world: Fixture
) -> None:
    """Sanity: the ids are real, so the outsider's 404s below mean isolation, not typos."""
    bad = []
    for route in world.routes:
        if SIGNED & set(PARAM.findall(route)) or STREAMS.search(route):
            continue
        url = _fill(route, world.owned.ids, world.cmp_finding)
        resp = await client.get(url, headers=world.owned.acct.headers)
        if resp.status_code in (401, 403, 404):
            bad.append(f"{route}: {resp.status_code}")
    assert not bad, "\n".join(bad)


async def _outsider(client: httpx.AsyncClient, role: Role) -> Account:
    admin = await register(client, org_name="Outsider Org")
    if role is Role.ORG_ADMIN:
        return admin
    person = await register(client, org_name="Outsider home")
    added = await client.post(
        f"/api/v1/organizations/{admin.organization_id}/members",
        headers=admin.headers,
        json={"email": person.email, "role": role.value},
    )
    assert added.status_code == 201, added.text
    return await login(client, person, organization_id=admin.organization_id)


@settings(
    max_examples=5, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(role=st.sampled_from(list(Role)))
async def test_another_organization_gets_404_everywhere_and_never_sees_an_id(
    client: httpx.AsyncClient, world: Fixture, role: Role
) -> None:
    outsider = await _outsider(client, role)
    leaks, wrong = [], []
    for route in world.routes:
        params = set(PARAM.findall(route))
        if SIGNED & params:
            continue
        if params:
            url = _fill(route, world.owned.ids, world.cmp_finding)
            resp = await client.get(url, headers=outsider.headers)
            # 403 is allowed only where the role lacks the permission (checked before lookup);
            # the resource still never reaches the caller.
            if resp.status_code not in (403, 404):
                wrong.append(f"{role.value} GET {route}: {resp.status_code}")
                continue
        else:
            resp = await client.get(route, headers=outsider.headers)
        if resp.status_code == 200 and resp.headers.get("content-type", "").startswith(
            "application/json"
        ):
            body = json.dumps(resp.json())
            found = {i for i in world.owned.all_ids if i in body}
            if found:
                leaks.append(f"{role.value} GET {route} leaked {sorted(found)}")
    assert not wrong, "\n".join(wrong)
    assert not leaks, "\n".join(leaks)
