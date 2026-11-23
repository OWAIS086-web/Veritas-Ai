# Req: evidence-explorer 2.4 (assignment and evidence requests on a finding)
"""Assigning a finding to an investigator and requesting documents for it, against the real
API: membership is checked, actions are audited, requests appear on the finding, the case and
the report, and another organization gets 404."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from app.integrations.storage.s3_store import get_store
from app.services.reporting import service as report_service
from tests.integration.conftest import register
from tests.integration.test_findings import Processed, _process

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
async def pair(app: Any) -> AsyncIterator[Processed]:
    transport = httpx.ASGITransport(app=app, client=("10.9.9.4", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield await _process(c, ["02_commercial_invoice.pdf", "03_customs_declaration.pdf"])


async def _finding(client: httpx.AsyncClient, p: Processed) -> str:
    rows = (await client.get(f"/api/v1/cases/{p.case_id}/findings", headers=p.acct.headers)).json()
    return str(next(f["id"] for f in rows if f["type"] == "financial_discrepancy"))


@pytest.mark.slow
async def test_assignment_is_limited_to_members_and_audited(
    client: httpx.AsyncClient, pair: Processed
) -> None:
    fid = await _finding(client, pair)
    h = pair.acct.headers
    resp = await client.patch(
        f"/api/v1/findings/{fid}/assignee", headers=h, json={"user_id": str(pair.acct.user_id)}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["assignee_user_id"] == str(pair.acct.user_id)
    assert resp.json()["assignee_email"] == pair.acct.email
    listed = (await client.get(f"/api/v1/cases/{pair.case_id}/findings", headers=h)).json()
    assert next(f for f in listed if f["id"] == fid)["assignee_user_id"] == str(pair.acct.user_id)
    # A user of another organization can't be assigned.
    stranger = await register(client, org_name="Not A Member")
    bad = await client.patch(
        f"/api/v1/findings/{fid}/assignee", headers=h, json={"user_id": str(stranger.user_id)}
    )
    assert bad.status_code == 422
    cleared = await client.patch(
        f"/api/v1/findings/{fid}/assignee", headers=h, json={"user_id": None}
    )
    assert cleared.status_code == 200 and cleared.json()["assignee_user_id"] is None
    logs = (await client.get("/api/v1/audit-logs", headers=h)).json()["items"]
    assert sum(e["action"] == "finding.assign" for e in logs) == 2


@pytest.mark.slow
async def test_evidence_requests_appear_on_the_finding_the_case_and_the_report(
    client: httpx.AsyncClient, pair: Processed
) -> None:
    fid = await _finding(client, pair)
    h = pair.acct.headers
    resp = await client.post(
        f"/api/v1/findings/{fid}/evidence-requests",
        headers=h,
        json={"document_types": ["freight_invoice", ""], "note": "Explain the USD 20,000 gap."},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["finding_id"] == fid and resp.json()["document_types"] == ["freight_invoice"]
    detail = (await client.get(f"/api/v1/findings/{fid}", headers=h)).json()
    assert [r["id"] for r in detail["evidence_requests"]] == [resp.json()["id"]]
    on_case = (
        await client.get(f"/api/v1/cases/{pair.case_id}/evidence-requests", headers=h)
    ).json()
    assert resp.json()["id"] in [r["id"] for r in on_case]
    empty = await client.post(
        f"/api/v1/findings/{fid}/evidence-requests",
        headers=h,
        json={"document_types": [" "], "note": "None"},
    )
    assert empty.status_code == 422

    report = await client.post(
        f"/api/v1/cases/{pair.case_id}/reports", headers=h, json={"format": "json"}
    )
    rid = report.json()["id"]
    await report_service.generate(pair.acct.organization_id, uuid.UUID(rid), get_store())
    model = (await client.get(f"/api/v1/reports/{rid}", headers=h)).json()["model"]
    requested = [
        x for x in model["missing_supporting_documents"] if x["source"] == "evidence_request"
    ]
    assert (
        requested
        and requested[0]["finding_id"] == fid
        and "freight_invoice" in requested[0]["text"]
    )


@pytest.mark.slow
async def test_review_actions_are_isolated_between_organizations(
    client: httpx.AsyncClient, pair: Processed
) -> None:
    fid = await _finding(client, pair)
    outsider = await register(client, org_name="Review Outsider")
    for method, path, body in [
        ("PATCH", f"/api/v1/findings/{fid}/assignee", {"user_id": str(outsider.user_id)}),
        (
            "POST",
            f"/api/v1/findings/{fid}/evidence-requests",
            {"document_types": ["x"], "note": "probe"},
        ),
    ]:
        resp = await client.request(method, path, headers=outsider.headers, json=body)
        assert resp.status_code == 404, f"{method} {path}: {resp.status_code}"
