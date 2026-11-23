# Req: cross-document-intelligence 2.1-2.2, 3.1, 4.1, 5.1-5.3; evidence-explorer 2.1-2.3
"""Cross-document comparison on the real pipeline output, persisted findings, review
decisions, database integrity triggers and tenant isolation."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.db import session_scope, set_tenant, tenant_session
from app.models import AuditLog, EvidenceItem, ExtractedField, Finding
from app.services.comparison.persist import run_comparison
from app.workers import comparison_tasks
from tests.integration.conftest import Account, register
from tests.integration.test_cases_and_upload import new_case, upload
from tests.integration.test_pipeline import run_job

pytestmark = pytest.mark.integration
CASE_DIR = Path(__file__).resolve().parents[3] / "sample-data" / "shipment-case"


@dataclass
class Processed:
    acct: Account
    case_id: str
    job_id: str


async def _process(client: httpx.AsyncClient, names: list[str] | None = None) -> Processed:
    acct = await register(client)
    case = await new_case(client, acct)
    paths = sorted(CASE_DIR.glob("*.pdf"))
    files = [(p.name, p.read_bytes()) for p in paths if names is None or p.name in names]
    body = await upload(client, acct, case["id"], files)
    assert (await run_job(acct, body["job_id"])).value == "succeeded"
    return Processed(acct, case["id"], body["job_id"])


@pytest.fixture(scope="module")
async def demo(app: Any) -> AsyncIterator[Processed]:
    """The full 7-document shipment case, processed once for this module."""
    transport = httpx.ASGITransport(app=app, client=("10.9.9.9", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield await _process(c)


@pytest.fixture(scope="module")
async def pair(app: Any) -> AsyncIterator[Processed]:
    """Invoice (USD 48,000) and customs declaration (USD 68,000) only."""
    transport = httpx.ASGITransport(app=app, client=("10.9.9.8", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield await _process(c, ["02_commercial_invoice.pdf", "03_customs_declaration.pdf"])


async def _findings(client: httpx.AsyncClient, p: Processed) -> list[dict[str, Any]]:
    resp = await client.get(f"/api/v1/cases/{p.case_id}/findings", headers=p.acct.headers)
    assert resp.status_code == 200, resp.text
    return list(resp.json())


@pytest.mark.slow
async def test_demo_case_yields_one_20000_usd_discrepancy_with_5_evidence_items(
    client: httpx.AsyncClient, demo: Processed
) -> None:
    findings = await _findings(client, demo)
    assert [f["type"] for f in findings] == ["financial_discrepancy"]
    [summary] = findings
    assert summary["difference"] == "20000.00" and summary["currency"] == "USD"
    assert summary["field"] == "total_amount" and summary["severity"] == "high"
    assert summary["anomaly_score"] == "0.294"
    assert summary["evidence_confidence"] == "1.000" and summary["priority"] == "high"
    assert summary["status"] == "new" and summary["evidence_count"] == 5
    assert summary["detected_by"] == "financial.total_amount@1.0"

    detail = (
        await client.get(f"/api/v1/findings/{summary['id']}", headers=demo.acct.headers)
    ).json()
    evidence = detail["evidence"]
    assert len(evidence) == 5
    assert {e["doc_type"] for e in evidence} == {
        "purchase_order",
        "commercial_invoice",
        "payment_receipt",
        "customs_declaration",
        "insurance_certificate",
    }
    assert sorted(e["normalized_value"]["amount"] for e in evidence) == (
        ["48000.00"] * 3 + ["68000.00"] * 2
    )
    # Every evidence item resolves to the real extracted field it cites.
    async with tenant_session(demo.acct.organization_id) as s:
        for e in evidence:
            row = await s.get(ExtractedField, uuid.UUID(e["extracted_field_id"]))
            assert row is not None and str(row.document_id) == e["document_id"]
            assert row.name == "total_amount" and row.value == e["value"]
            assert row.page_number == e["page_number"] and row.bbox == e["bbox"]
    customs = next(e for e in evidence if e["doc_type"] == "customs_declaration")
    assert customs["page_number"] == 2
    assert detail["ai_output_json"]["detector"] == "rules"
    assert detail["ai_output_json"]["model"] is None
    assert detail["coverage"]["skipped"] == []
    assert any("CIF" in note for note in detail["limitations"])

    case = (await client.get(f"/api/v1/cases/{demo.case_id}", headers=demo.acct.headers)).json()
    assert case["finding_count"] == 1 and case["compared_at"] is not None
    job = (await client.get(f"/api/v1/jobs/{demo.job_id}", headers=demo.acct.headers)).json()
    [comparison] = job["result"]["comparisons"]
    assert comparison["findings"] == 1 and comparison["rules_failed"] == {}
    stats = (await client.get("/api/v1/stats/overview", headers=demo.acct.headers)).json()
    assert stats["findings_requiring_review"]["value"] == 1
    assert stats["high_priority_findings"]["value"] == 1


@pytest.mark.slow
async def test_rerun_is_idempotent_and_keeps_the_human_status(
    client: httpx.AsyncClient, demo: Processed
) -> None:
    [before] = await _findings(client, demo)
    headers = demo.acct.headers
    changed = await client.patch(
        f"/api/v1/findings/{before['id']}/status", headers=headers, json={"status": "under_review"}
    )
    assert changed.status_code == 200, changed.text
    first = (await client.get(f"/api/v1/findings/{before['id']}", headers=headers)).json()

    # Through the API and the worker task (without the broker), then directly once more.
    started = await client.post(f"/api/v1/cases/{demo.case_id}/compare", headers=headers)
    assert started.status_code == 202
    job_id = uuid.UUID(started.json()["job_id"])
    outcome = await comparison_tasks._run(demo.acct.organization_id, job_id)
    assert outcome.value == "succeeded"
    async with tenant_session(demo.acct.organization_id) as s:
        summary = await run_comparison(s, demo.acct.organization_id, uuid.UUID(demo.case_id))
    assert summary["created"] == 0 and summary["updated"] == 1

    [after] = await _findings(client, demo)
    second = (await client.get(f"/api/v1/findings/{after['id']}", headers=headers)).json()
    assert after["id"] == before["id"] and after["status"] == "under_review"
    assert [e["id"] for e in second["evidence"]] == [e["id"] for e in first["evidence"]]
    assert second["ai_output_json"] == first["ai_output_json"]
    assert [d["to_status"] for d in second["decisions"]] == ["under_review"]
    async with tenant_session(demo.acct.organization_id) as s:
        assert len(list(await s.scalars(select(Finding.id)))) == 1


@pytest.mark.slow
async def test_review_decisions_notes_and_the_evidence_rule(
    client: httpx.AsyncClient, pair: Processed
) -> None:
    headers = pair.acct.headers
    findings = await _findings(client, pair)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        by_type.setdefault(f["type"], []).append(f)
    [financial] = by_type["financial_discrepancy"]
    assert financial["evidence_count"] == 2 and financial["difference"] == "20000.00"
    # Four expected document types are absent from this two-document case.
    missing = by_type["missing_document"]
    assert len(missing) == 4 and all(m["evidence_status"] == "absence" for m in missing)
    assert set(by_type) == {"financial_discrepancy", "missing_document"}

    url = f"/api/v1/findings/{financial['id']}/status"
    no_note = await client.patch(url, headers=headers, json={"status": "dismissed"})
    assert no_note.status_code == 422
    confirmed = await client.patch(
        url,
        headers=headers,
        json={"status": "confirmed_observation", "note": "Values verified on each page."},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "confirmed_observation"
    assert body["decisions"][-1]["from_status"] == "new"
    assert body["decisions"][-1]["note"] == "Values verified on each page."
    assert body["decisions"][-1]["actor_email"] == pair.acct.email
    again = await client.patch(
        url, headers=headers, json={"status": "confirmed_observation", "note": "again"}
    )
    assert again.status_code == 409

    absent = await client.patch(
        f"/api/v1/findings/{missing[0]['id']}/status",
        headers=headers,
        json={"status": "confirmed_observation", "note": "Confirmed missing."},
    )
    assert absent.status_code == 409
    assert "without evidence" in absent.json()["detail"]
    needs = await client.patch(
        f"/api/v1/findings/{missing[0]['id']}/status",
        headers=headers,
        json={"status": "needs_more_evidence"},
    )
    assert needs.status_code == 200

    comment = await client.post(
        f"/api/v1/findings/{financial['id']}/comments",
        headers=headers,
        json={"body": "Asked the broker for the valuation worksheet."},
    )
    assert comment.status_code == 201
    detail = (await client.get(f"/api/v1/findings/{financial['id']}", headers=headers)).json()
    assert [c["body"] for c in detail["comments"]] == [
        "Asked the broker for the valuation worksheet."
    ]
    # The review left the detector's original output untouched.
    assert detail["ai_output_json"]["output"]["severity"] == "high"
    assert "status" not in detail["ai_output_json"]["output"]
    async with tenant_session(pair.acct.organization_id) as s:
        actions = list(
            await s.scalars(select(AuditLog.action).where(AuditLog.resource_id == financial["id"]))
        )
    assert actions.count("finding.review") == 1 and actions.count("finding.comment") == 1

    listing = await client.get(
        "/api/v1/findings", headers=headers, params={"type": "missing_document", "limit": 3}
    )
    page = listing.json()
    assert len(page["items"]) == 3 and page["next_cursor"]
    rest = await client.get(
        "/api/v1/findings",
        headers=headers,
        params={"type": "missing_document", "limit": 3, "cursor": page["next_cursor"]},
    )
    ids = {f["id"] for f in page["items"]} | {f["id"] for f in rest.json()["items"]}
    assert ids == {m["id"] for m in missing}


@pytest.mark.slow
async def test_database_triggers_and_append_only_tables(
    client: httpx.AsyncClient, pair: Processed
) -> None:
    org = pair.acct.organization_id
    async with tenant_session(org) as s:
        case_id = uuid.UUID(pair.case_id)
        rows = list(await s.scalars(select(Finding).where(Finding.case_id == case_id)))
        absent = next(f for f in rows if f.type == "missing_document" and f.status == "new")
        supported = next(f for f in rows if f.type == "financial_discrepancy")
        item = await s.scalar(select(EvidenceItem).where(EvidenceItem.finding_id == supported.id))
        assert item is not None
        absent_id, supported_id, evidence_doc = absent.id, supported.id, item.document_id

    async def fails(sql: str, params: dict[str, Any], message: str) -> None:
        with pytest.raises(DBAPIError, match=message):
            async with session_scope() as s:
                await set_tenant(s, org)
                await s.execute(text(sql), params)

    # Confirmation without evidence is refused by the database itself.
    await fails(
        "UPDATE findings SET status = 'confirmed_observation' WHERE id = :id",
        {"id": absent_id},
        "finding_requires_evidence",
    )
    await fails(
        "UPDATE findings SET ai_output_json = '{}'::jsonb WHERE id = :id",
        {"id": supported_id},
        "ai_output_json_is_immutable",
    )
    # Evidence must point at a document of the finding's own case: not another case of the
    # same organization, and not another organization's document (invisible under RLS).
    receipt = [("05_payment_receipt.pdf", (CASE_DIR / "05_payment_receipt.pdf").read_bytes())]
    other_case = await new_case(client, pair.acct, title="Unrelated case")
    same_org_doc = (await upload(client, pair.acct, other_case["id"], receipt))["results"][0]
    outsider = await register(client, org_name="Evidence Outsider")
    outsider_case = await new_case(client, outsider)
    foreign_doc = (await upload(client, outsider, outsider_case["id"], receipt))["results"][0]
    insert = (
        "INSERT INTO evidence_items (id, organization_id, finding_id, document_id, field_name,"
        " role, created_at) VALUES (gen_random_uuid(), :org, :f, :d, 'x', 'context', now())"
    )
    for doc in (same_org_doc["document_id"], foreign_doc["document_id"]):
        await fails(insert, {"org": org, "f": supported_id, "d": doc}, "evidence_outside_case")
    await fails(
        "INSERT INTO evidence_items (id, organization_id, finding_id, document_id,"
        " extracted_field_id, field_name, role, created_at) VALUES (gen_random_uuid(), :org, :f,"
        " :d, :x, 'x', 'context', now())",
        {"org": org, "f": supported_id, "d": evidence_doc, "x": uuid.uuid4()},
        "evidence_field_mismatch|violates foreign key",
    )
    for statement in (
        "UPDATE finding_decisions SET note = 'edited'",
        "DELETE FROM finding_decisions",
        "UPDATE investigator_comments SET body = 'edited'",
        "DELETE FROM findings",
    ):
        await fails(statement, {}, "permission denied")


@pytest.mark.slow
async def test_findings_are_isolated_between_organizations(
    client: httpx.AsyncClient, pair: Processed
) -> None:
    outsider = await register(client, org_name="Other Org")
    [finding, *_] = await _findings(client, pair)
    fid, cid = finding["id"], pair.case_id
    h = outsider.headers
    for method, path, body in [
        ("GET", f"/api/v1/findings/{fid}", None),
        ("GET", f"/api/v1/findings/{fid}/evidence", None),
        ("PATCH", f"/api/v1/findings/{fid}/status", {"status": "under_review"}),
        ("POST", f"/api/v1/findings/{fid}/comments", {"body": "probe"}),
        ("GET", f"/api/v1/cases/{cid}/findings", None),
        ("POST", f"/api/v1/cases/{cid}/compare", None),
    ]:
        resp = await client.request(method, path, headers=h, json=body)
        assert resp.status_code == 404, f"{method} {path}: {resp.status_code}"
    listed = (await client.get("/api/v1/findings", headers=h)).json()
    assert listed["items"] == []
    for table in ("findings", "evidence_items", "finding_decisions", "investigator_comments"):
        async with session_scope() as s:
            await set_tenant(s, outsider.organization_id)
            seen = (await s.scalars(text(f"SELECT organization_id FROM {table}"))).all()  # noqa: S608
        assert seen == [], table
        async with session_scope() as s:
            unscoped = (await s.scalars(text(f"SELECT organization_id FROM {table}"))).all()  # noqa: S608
        assert unscoped == [], f"{table} visible without tenant context"
    async with session_scope() as s:
        await set_tenant(s, pair.acct.organization_id)
        own = set((await s.scalars(text("SELECT organization_id FROM findings"))).all())
    assert own == {pair.acct.organization_id}


async def test_comparing_an_empty_case_creates_nothing(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    case = await new_case(client, acct)
    async with tenant_session(acct.organization_id) as s:
        summary = await run_comparison(s, acct.organization_id, uuid.UUID(case["id"]))
    assert summary["findings"] == 0 and summary["documents_compared"] == 0
    fresh = (await client.get(f"/api/v1/cases/{case['id']}", headers=acct.headers)).json()
    assert fresh["finding_count"] == 0 and fresh["compared_at"] is not None
    assert summary["created"] == 0
