"""Reports end to end against real Postgres and object storage: the demo case's report in all
four formats, the citation and summary verifiers, the approval gate, review-status labels,
signed downloads with an integrity check, and tenant isolation."""

from __future__ import annotations

import hashlib
import io
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pymupdf
import pytest
from docx import Document as DocxDocument
from openpyxl import load_workbook
from sqlalchemy import text

from app.core.db import session_scope, set_tenant
from app.core.signing import REPORT_ARTIFACT, sign
from app.integrations.storage.s3_store import get_store
from app.services.investigations.run import run_investigation
from app.services.reporting import model as m
from app.services.reporting import service as report_service
from tests.agent_provider import ScriptedProvider
from tests.integration.conftest import register
from tests.integration.test_findings import Processed, _process

pytestmark = pytest.mark.integration
# The demo finding's evidence: (filename, page) per document (shipment-case ground truth).
EVIDENCE_PAGES = {
    "01_purchase_order.pdf": 1,
    "02_commercial_invoice.pdf": 1,
    "03_customs_declaration.pdf": 2,
    "04_insurance_certificate.pdf": 1,
    "05_payment_receipt.pdf": 1,
}
LIGATURES_EXPANDED = pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_PRESERVE_LIGATURES


@pytest.fixture(scope="module")
async def case(app: Any) -> AsyncIterator[Processed]:
    transport = httpx.ASGITransport(app=app, client=("10.9.9.5", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield await _process(c)


async def _request(
    client: httpx.AsyncClient, p: Processed, fmt: str, investigation_id: str | None = None
) -> httpx.Response:
    body: dict[str, Any] = {"format": fmt}
    if investigation_id:
        body["investigation_id"] = investigation_id
    return await client.post(
        f"/api/v1/cases/{p.case_id}/reports", headers=p.acct.headers, json=body
    )


async def _generated(
    client: httpx.AsyncClient, p: Processed, fmt: str, **kw: Any
) -> dict[str, Any]:
    resp = await _request(client, p, fmt, **kw)
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "queued"
    rid = resp.json()["id"]
    await report_service.generate(p.acct.organization_id, uuid.UUID(rid), get_store())
    detail = await client.get(f"/api/v1/reports/{rid}", headers=p.acct.headers)
    assert detail.status_code == 200, detail.text
    return dict(detail.json())


async def _file(client: httpx.AsyncClient, p: Processed, rid: str) -> httpx.Response:
    link = await client.get(f"/api/v1/reports/{rid}/download", headers=p.acct.headers)
    assert link.status_code == 200, link.text
    resp = await client.get(link.json()["url"])  # signed: no bearer token
    assert resp.status_code == 200, resp.text
    return resp


def _money(model: dict[str, Any]) -> dict[str, Any]:
    [money] = [d for d in model["identified_discrepancies"] if d["type"] == "financial_discrepancy"]
    return dict(money)


@pytest.mark.slow
async def test_the_demo_report_cites_the_evidence_in_every_format(
    client: httpx.AsyncClient, case: Processed
) -> None:
    reports = {fmt: await _generated(client, case, fmt) for fmt in ("json", "pdf", "docx", "xlsx")}
    for fmt, r in reports.items():
        assert r["status"] == "completed", (fmt, r["error"])
        assert r["sha256"] and r["size_bytes"] and r["findings_total"] >= 1
    model = reports["json"]["model"]
    assert model["label"] == "SYNTHETIC DEMONSTRATION DATA"
    money = _money(model)
    assert "20,000.00" in money["title"]
    assert money["review_label"] == m.NOT_REVIEWED
    cited = {c["filename"]: c["page"] for c in money["evidence"]}
    assert cited == EVIDENCE_PAGES
    assert {c["finding_id"] for c in money["evidence"]} == {money["finding_id"]}
    assert all(c["value"] and c["document_id"] for c in money["evidence"])
    assert model["audit"]["summary_method"] == "template"
    assert model["forensic_observations"] == []  # the shipment samples are clean
    assert model["limitations"][0].startswith("This report states observations")

    # Each file opens with its library and carries the finding id and its citations.
    pdf = await _file(client, case, reports["pdf"]["id"])
    assert hashlib.sha256(pdf.content).hexdigest() == reports["pdf"]["sha256"]
    assert pdf.headers["x-report-sha256"] == reports["pdf"]["sha256"]
    assert pdf.headers["content-disposition"].startswith('attachment; filename="veritas-report-')
    with pymupdf.open(stream=pdf.content, filetype="pdf") as doc:
        pdf_text = " ".join(pg.get_text(flags=LIGATURES_EXPANDED) for pg in doc).replace("\n", " ")
    for needle in (
        money["finding_id"],
        "03_customs_declaration.pdf",
        m.NOT_REVIEWED,
        "Audit information",
    ):
        assert needle in pdf_text, needle
    docx = DocxDocument(io.BytesIO((await _file(client, case, reports["docx"]["id"])).content))
    assert [p.text for p in docx.paragraphs if p.style.name == "Heading 1"] == [
        t for _, t in m.SECTIONS
    ]
    wb = load_workbook(io.BytesIO((await _file(client, case, reports["xlsx"]["id"])).content))
    evidence_rows = list(wb["Evidence references"].iter_rows(values_only=True))[1:]
    pages = {(r[1], r[3]) for r in evidence_rows if r[0] == money["finding_id"]}
    assert pages == {(name, str(page)) for name, page in EVIDENCE_PAGES.items()}

    history = (
        await client.get(f"/api/v1/cases/{case.case_id}/reports", headers=case.acct.headers)
    ).json()
    assert {h["format"] for h in history} >= {"json", "pdf", "docx", "xlsx"}
    assert all(h["created_by_email"] == case.acct.email for h in history)
    logs = (await client.get("/api/v1/audit-logs?limit=100", headers=case.acct.headers)).json()
    actions = {e["action"] for e in logs["items"]}
    assert {"report.request", "report.generated", "report.access", "report.download"} <= actions


@pytest.mark.slow
async def test_review_decisions_are_reported_per_finding(
    client: httpx.AsyncClient, case: Processed
) -> None:
    before = await _generated(client, case, "json")
    fid = _money(before["model"])["finding_id"]
    resp = await client.patch(
        f"/api/v1/findings/{fid}/status",
        headers=case.acct.headers,
        json={"status": "under_review", "note": "Checking the valuation basis."},
    )
    assert resp.status_code == 200, resp.text
    after = await _generated(client, case, "json")
    assert _money(after["model"])["review_label"] == "Under review"
    assert after["findings_not_reviewed"] == before["findings_not_reviewed"] - 1


@pytest.mark.slow
async def test_an_orphan_reference_fails_the_export_with_the_bad_references(
    client: httpx.AsyncClient, case: Processed, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = report_service.build_report
    ghost_finding, ghost_doc = uuid.uuid4(), uuid.uuid4()

    async def with_orphan(*args: Any, **kwargs: Any) -> m.ReportModel:
        model = await real(*args, **kwargs)
        model.evidence_references.append(
            m.Citation(
                finding_id=ghost_finding,
                document_id=ghost_doc,
                filename="invented.pdf",
                page=3,
                field_name="total_amount",
                value="USD 1.00",
            )
        )
        return model

    monkeypatch.setattr(report_service, "build_report", with_orphan)
    r = await _generated(client, case, "pdf")
    assert r["status"] == "failed" and r["sha256"] is None
    assert "document_not_in_case" in r["error"] and str(ghost_doc) in r["error"]
    link = await client.get(f"/api/v1/reports/{r['id']}/download", headers=case.acct.headers)
    assert link.status_code == 409


@pytest.mark.slow
async def test_an_invented_number_in_the_summary_fails_the_export(
    client: httpx.AsyncClient, case: Processed, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = report_service.build_report

    async def with_invention(*args: Any, **kwargs: Any) -> m.ReportModel:
        model = await real(*args, **kwargs)
        model.executive_summary += " A further USD 999,999.00 was paid in cash."
        return model

    monkeypatch.setattr(report_service, "build_report", with_invention)
    r = await _generated(client, case, "docx")
    assert r["status"] == "failed"
    assert "summary_value_not_in_content: 999999" in r["error"]


@pytest.mark.slow
async def test_reports_from_an_investigation_need_its_approval(
    client: httpx.AsyncClient, case: Processed
) -> None:
    org = case.acct.organization_id
    started = await client.post(
        f"/api/v1/cases/{case.case_id}/investigate",
        headers=case.acct.headers,
        json={"objective": "Explain the declared value difference"},
    )
    inv = started.json()["id"]
    assert (await _request(client, case, "pdf", inv)).status_code == 409  # queued
    assert await run_investigation(org, uuid.UUID(inv), ScriptedProvider()) == "awaiting_review"
    resp = await _request(client, case, "pdf", inv)
    assert resp.status_code == 409 and "approved" in resp.json()["detail"]
    await client.post(f"/api/v1/investigations/{inv}/approve", headers=case.acct.headers)
    assert await run_investigation(org, uuid.UUID(inv), ScriptedProvider()) == "completed"

    r = await _generated(client, case, "json", investigation_id=inv)
    assert r["status"] == "completed", r["error"]
    model = r["model"]
    assert model["investigation_id"] == inv
    assert model["audit"]["investigation_approved_by"] == case.acct.email
    assert model["audit"]["summary_method"] == "investigation_model"
    assert "20000.00" in model["executive_summary"]
    hypotheses = model["alternative_explanations"]
    assert hypotheses and all(h["hypothesis"] for h in hypotheses)
    assert any("CIF" in h["text"] for h in hypotheses)
    # All 7 documents are present, so no comparison rule reports an absence here; the
    # investigation's suggestion (a freight invoice) is carried into the report.
    missing = model["missing_supporting_documents"]
    assert {x["source"] for x in missing} == {"investigation"}
    assert any("freight" in x["text"] for x in missing)


@pytest.mark.slow
async def test_report_links_and_document_links_cannot_stand_in_for_each_other(
    client: httpx.AsyncClient, case: Processed
) -> None:
    r = await _generated(client, case, "json")
    link = (
        await client.get(f"/api/v1/reports/{r['id']}/download", headers=case.acct.headers)
    ).json()
    token = link["url"].rsplit("/", 1)[1]
    assert (await client.get(f"/api/v1/files/{token}")).status_code == 403
    assert (await client.get(f"/api/v1/report-files/{token[:-2]}xx")).status_code == 403
    doc_id = r["model"]["documents_analyzed"][0]["document_id"]
    preview = (
        await client.get(f"/api/v1/documents/{doc_id}/preview", headers=case.acct.headers)
    ).json()
    doc_token = preview["url"].rsplit("/", 1)[1]
    assert (await client.get(f"/api/v1/report-files/{doc_token}")).status_code == 403
    expired, _ = sign(uuid.UUID(r["id"]), case.acct.organization_id, -5, artifact=REPORT_ARTIFACT)
    assert (await client.get(f"/api/v1/report-files/{expired}")).status_code == 403
    # A finished report is never generated again.
    org = case.acct.organization_id
    assert await report_service.generate(org, uuid.UUID(r["id"]), get_store()) == "completed"


@pytest.mark.slow
async def test_reports_are_isolated_between_organizations(
    client: httpx.AsyncClient, case: Processed
) -> None:
    r = await _generated(client, case, "json")
    outsider = await register(client, org_name="Report Outsider")
    for method, path, body in [
        ("POST", f"/api/v1/cases/{case.case_id}/reports", {"format": "pdf"}),
        ("GET", f"/api/v1/cases/{case.case_id}/reports", None),
        ("GET", f"/api/v1/reports/{r['id']}", None),
        ("GET", f"/api/v1/reports/{r['id']}/download", None),
    ]:
        resp = await client.request(method, path, headers=outsider.headers, json=body)
        assert resp.status_code == 404, f"{method} {path}: {resp.status_code}"
    # A link signed for another organization doesn't reach this report.
    foreign, _ = sign(uuid.UUID(r["id"]), outsider.organization_id, 60, artifact=REPORT_ARTIFACT)
    assert (await client.get(f"/api/v1/report-files/{foreign}")).status_code == 404
    async with session_scope() as s:
        await set_tenant(s, outsider.organization_id)
        assert (await s.scalars(text("SELECT id FROM reports"))).all() == []
    async with session_scope() as s:
        assert (await s.scalars(text("SELECT id FROM reports"))).all() == []
