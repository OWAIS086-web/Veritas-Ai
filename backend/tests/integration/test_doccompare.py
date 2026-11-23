"""Document comparison lab end to end against real Postgres and object storage: the upload pair
goes through the real processing pipeline, the comparison worker waits for it, the findings
match the fixture manifest, the exports are real files with verified hashes, human review is
audited, and every endpoint is isolated between organizations."""

from __future__ import annotations

import hashlib
import io
import json
import uuid
import zipfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pymupdf
import pytest
from sqlalchemy import select, text

from app.core.db import session_scope, set_tenant, tenant_session
from app.core.signing import COMPARISON_EXPORT_ARTIFACT, REPORT_ARTIFACT, sign
from app.integrations.llm.replay import ReplayProvider
from app.integrations.storage.s3_store import get_store
from app.models import AuditLog, ComparisonExport, Document, ExtractedField
from app.services.doccompare.geometry import overlaps
from app.services.doccompare.run import generate_export, queued_exports, run_comparison
from app.services.doccompare.vision import Vision, VisionStats
from tests.integration.conftest import Account, login, register
from tests.integration.test_cases_and_upload import new_case, upload
from tests.integration.test_pipeline import run_job

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3] / "sample-data" / "comparison"
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
RECORDED = (
    Path(__file__).resolve().parents[1] / "fixtures" / "llm" / "doccompare_vision_altered.json"
)
TABLES = ("document_comparisons", "comparison_findings", "comparison_reviews", "comparison_exports")


async def no_vision() -> tuple[Vision | None, str, str | None]:
    return None, "disabled", "disabled in this test"


async def recorded_vision() -> tuple[Vision | None, str, str | None]:
    provider = ReplayProvider.from_file(RECORDED)
    return Vision(provider, "qwen2.5vl:7b", VisionStats(model="qwen2.5vl:7b")), "used", None


@dataclass
class Lab:
    acct: Account
    case_id: str
    comparison_id: str
    original_id: str
    test_id: str
    waited: str


def _files(*names: str) -> dict[str, tuple[str, bytes, str]]:
    mime = {"pdf": "application/pdf", "png": "image/png", "csv": "text/csv"}
    return {
        role: (name, (ROOT / name).read_bytes(), mime[name.rsplit(".", 1)[1]])
        for role, name in zip(("original", "test"), names, strict=True)
    }


async def _upload_pair(
    c: httpx.AsyncClient, acct: Account, case_id: str, original: str, test: str
) -> httpx.Response:
    return await c.post(
        f"/api/v1/cases/{case_id}/comparisons/upload",
        headers=acct.headers,
        files=_files(original, test),
    )


async def _export_all(acct: Account, comparison_id: str) -> None:
    for eid in await queued_exports(acct.organization_id, uuid.UUID(comparison_id)):
        assert await generate_export(acct.organization_id, eid, get_store()) == "completed"


@pytest.fixture(scope="module")
async def lab(app: Any) -> AsyncIterator[Lab]:
    transport = httpx.ASGITransport(app=app, client=("10.9.9.11", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        acct = await register(c, org_name="Comparison Lab Org")
        case = await new_case(c, acct, title="Invoice comparison")
        resp = await _upload_pair(c, acct, case["id"], "original_invoice.pdf", "test_altered.pdf")
        assert resp.status_code == 202, resp.text
        body = resp.json()
        cid = body["comparison"]["id"]
        # The worker waits while the documents are still being processed.
        waited = await run_comparison(acct.organization_id, uuid.UUID(cid), get_store(), no_vision)
        assert (await run_job(acct, body["job_id"])).value == "succeeded"
        result = await run_comparison(
            acct.organization_id, uuid.UUID(cid), get_store(), recorded_vision
        )
        assert result == "completed"
        await _export_all(acct, cid)
        yield Lab(
            acct,
            case["id"],
            cid,
            body["original"]["document_id"],
            body["test"]["document_id"],
            waited,
        )


async def _detail(c: httpx.AsyncClient, lab: Lab) -> dict[str, Any]:
    resp = await c.get(f"/api/v1/comparisons/{lab.comparison_id}", headers=lab.acct.headers)
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


@pytest.mark.slow
async def test_upload_queues_processing_and_the_worker_waits_for_it(
    client: httpx.AsyncClient, lab: Lab, no_broker: list[tuple[uuid.UUID, uuid.UUID]]
) -> None:
    assert lab.waited == "waiting"
    listed = await client.get(f"/api/v1/cases/{lab.case_id}/comparisons", headers=lab.acct.headers)
    assert listed.status_code == 200
    [row] = listed.json()
    assert row["id"] == lab.comparison_id and row["status"] == "completed"
    assert row["original_filename"] == "original_invoice.pdf"
    assert row["test_filename"] == "test_altered.pdf"
    assert row["progress"] == 100 and row["findings_count"] == 3


@pytest.mark.slow
async def test_findings_match_the_planted_changes_with_validated_regions(
    client: httpx.AsyncClient, lab: Lab
) -> None:
    d = await _detail(client, lab)
    assert d["status"] == "completed" and d["vlm_status"] == "used"
    assert d["vlm_model"] == "qwen2.5vl:7b"
    assert d["summary"]["original"]["sha256"] == MANIFEST["files"]["original_invoice.pdf"]["sha256"]
    assert d["summary"]["test"]["sha256"] == MANIFEST["files"]["test_altered.pdf"]["sha256"]
    assert d["summary"]["vlm"]["calls"] == 4 and d["summary"]["vlm"]["boxes_accepted"] == 0
    findings = d["findings"]
    assert [f["number"] for f in findings] == [1, 2, 3]
    for key in MANIFEST["expected"]["test_altered.pdf"]:
        change = MANIFEST["changes"][key]
        hits = [
            f
            for f in findings
            if f["test_page"] == change["page"] and overlaps(f["region"], change["box"])
        ]
        assert len(hits) == 1, key
        f = hits[0]
        assert f["severity"] == "medium" and f["test_text"] in change["test"]
        assert set(f["sources"]) >= {"ocr", "vlm"}
        assert f["vlm_assessment"]["status"] == "assessed"
        assert 0 < float(f["evidence_confidence"]) <= 0.95
        x0, y0, x1, y1 = f["region"]
        assert 0 <= x0 < x1 <= 595 and 0 <= y0 < y1 <= 842
        words = f["explanation"].lower()
        assert "forged" not in words and "authentic" not in words
    assert "forged or authentic" in d["limitation"]


@pytest.mark.slow
async def test_field_references_resolve_to_the_documents_extracted_fields(
    client: httpx.AsyncClient, lab: Lab
) -> None:
    d = await _detail(client, lab)
    refs = [r for f in d["findings"] for r in f["metrics"]["extracted_fields"]]
    assert any(r["name"] == "total_amount" for r in refs), refs
    docs = {"test": lab.test_id, "original": lab.original_id}
    async with tenant_session(lab.acct.organization_id) as s:
        for r in refs:
            field = await s.get(ExtractedField, uuid.UUID(r["id"]))
            assert field is not None and str(field.document_id) == docs[r["document"]]


@pytest.mark.slow
async def test_exports_are_real_files_served_through_signed_links(
    client: httpx.AsyncClient, lab: Lab
) -> None:
    exports = (
        await client.get(
            f"/api/v1/comparisons/{lab.comparison_id}/exports", headers=lab.acct.headers
        )
    ).json()
    assert {e["kind"] for e in exports} == {
        "annotated_pdf",
        "annotated_images",
        "report_pdf",
        "findings_json",
    }
    files: dict[str, bytes] = {}
    for e in exports:
        assert e["status"] == "completed" and e["sha256"]
        link = await client.get(
            f"/api/v1/comparison-exports/{e['id']}/download", headers=lab.acct.headers
        )
        assert link.status_code == 200, link.text
        resp = await client.get(link.json()["url"])  # no bearer token: the link is the grant
        assert resp.status_code == 200, resp.text
        assert hashlib.sha256(resp.content).hexdigest() == e["sha256"]
        assert resp.headers["x-export-sha256"] == e["sha256"]
        assert "attachment" in resp.headers["content-disposition"]
        files[e["kind"]] = resp.content
    with pymupdf.open(stream=files["annotated_pdf"], filetype="pdf") as doc:
        assert len(doc) >= 3  # two document pages plus the numbered list
        squares = [a for p in doc for a in p.annots() if a.type[1] == "Square"]
        assert len(squares) == 3
    assert (
        "test-page-001-annotated.png"
        in zipfile.ZipFile(io.BytesIO(files["annotated_images"])).namelist()
    )
    with pymupdf.open(stream=files["report_pdf"], filetype="pdf") as doc:
        text_ = "".join(p.get_text() for p in doc)
        assert "68,000.00" in text_ and "48,000.00" in text_
    data = json.loads(files["findings_json"])
    assert data["schema"] == "veritas.document-comparison.v1" and len(data["findings"]) == 3
    # The stored test original is untouched.
    async with tenant_session(lab.acct.organization_id) as s:
        doc_row = await s.get(Document, uuid.UUID(lab.test_id))
        assert doc_row is not None
        key = doc_row.storage_key
    original = await get_store().get(key)
    assert hashlib.sha256(original).hexdigest() == MANIFEST["files"]["test_altered.pdf"]["sha256"]


@pytest.mark.slow
async def test_signed_links_only_work_on_their_own_endpoint(
    client: httpx.AsyncClient, lab: Lab
) -> None:
    org = lab.acct.organization_id
    async with tenant_session(org) as s:
        export_id = await s.scalar(
            select(ComparisonExport.id).where(
                ComparisonExport.comparison_id == uuid.UUID(lab.comparison_id)
            )
        )
    assert export_id is not None
    token, _ = sign(export_id, org, 60, artifact=COMPARISON_EXPORT_ARTIFACT)
    assert (await client.get(f"/api/v1/files/{token}")).status_code == 403
    assert (await client.get(f"/api/v1/report-files/{token}")).status_code == 403
    doc_token, _ = sign(uuid.UUID(lab.test_id), org, 60)
    assert (await client.get(f"/api/v1/comparison-files/{doc_token}")).status_code == 403
    report_token, _ = sign(export_id, org, 60, artifact=REPORT_ARTIFACT)
    assert (await client.get(f"/api/v1/comparison-files/{report_token}")).status_code == 403
    expired, _ = sign(export_id, org, -5, artifact=COMPARISON_EXPORT_ARTIFACT)
    assert (await client.get(f"/api/v1/comparison-files/{expired}")).status_code == 403


async def _member(client: httpx.AsyncClient, admin: Account, role: str) -> Account:
    person = await register(client, org_name=f"Home of {role}")
    added = await client.post(
        f"/api/v1/organizations/{admin.organization_id}/members",
        headers=admin.headers,
        json={"email": person.email, "role": role},
    )
    assert added.status_code == 201, added.text
    return await login(client, person, organization_id=admin.organization_id)


@pytest.mark.slow
async def test_review_is_append_only_audited_and_drives_the_annotations(
    client: httpx.AsyncClient, lab: Lab
) -> None:
    d = await _detail(client, lab)
    first, second = d["findings"][0], d["findings"][1]
    base = f"/api/v1/comparisons/{lab.comparison_id}/findings"
    reviewer = await _member(client, lab.acct, "reviewer")
    analyst = await _member(client, lab.acct, "read_only_analyst")
    denied = await client.patch(
        f"{base}/{first['id']}/review",
        headers=analyst.headers,
        json={"status": "dismissed", "note": "x"},
    )
    assert denied.status_code == 403
    no_note = await client.patch(
        f"{base}/{first['id']}/review",
        headers=reviewer.headers,
        json={"status": "confirmed_difference"},
    )
    assert no_note.status_code == 422
    for status_, note in (
        ("needs_more_evidence", None),
        ("confirmed_difference", "Matches the PO."),
    ):
        resp = await client.patch(
            f"{base}/{first['id']}/review",
            headers=reviewer.headers,
            json={"status": status_, "note": note},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["review_status"] == status_
    dismissed = await client.patch(
        f"{base}/{second['id']}/review",
        headers=reviewer.headers,
        json={"status": "dismissed", "note": "Typo fixed with the buyer's consent."},
    )
    assert dismissed.status_code == 200
    history = (await client.get(f"{base}/{first['id']}/reviews", headers=analyst.headers)).json()
    assert [(h["from_status"], h["to_status"]) for h in history] == [
        ("unreviewed", "needs_more_evidence"),
        ("needs_more_evidence", "confirmed_difference"),
    ]
    assert history[1]["note"] == "Matches the PO." and history[1]["actor_email"] == reviewer.email
    async with tenant_session(lab.acct.organization_id) as s:
        audited = await s.scalar(
            select(AuditLog.id).where(
                AuditLog.action == "comparison.review",
                AuditLog.resource_id == first["id"],
            )
        )
        assert audited is not None
    # A new annotated copy leaves out the dismissed difference; the JSON keeps all of them.
    for kind in ("annotated_pdf", "findings_json"):
        resp = await client.post(
            f"/api/v1/comparisons/{lab.comparison_id}/exports",
            headers=lab.acct.headers,
            json={"kind": kind},
        )
        assert resp.status_code == 202, resp.text
        assert (
            await generate_export(
                lab.acct.organization_id, uuid.UUID(resp.json()["id"]), get_store()
            )
            == "completed"
        )
    exports = (
        await client.get(
            f"/api/v1/comparisons/{lab.comparison_id}/exports", headers=lab.acct.headers
        )
    ).json()
    newest: dict[str, dict[str, Any]] = {}
    for e in exports:  # newest first
        newest.setdefault(e["kind"], e)
    link = await client.get(
        f"/api/v1/comparison-exports/{newest['annotated_pdf']['id']}/download",
        headers=lab.acct.headers,
    )
    pdf = (await client.get(link.json()["url"])).content
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        assert len([a for p in doc for a in p.annots() if a.type[1] == "Square"]) == 2
    link = await client.get(
        f"/api/v1/comparison-exports/{newest['findings_json']['id']}/download",
        headers=lab.acct.headers,
    )
    statuses = [
        f["review_status"]
        for f in json.loads((await client.get(link.json()["url"])).content)["findings"]
    ]
    assert statuses.count("dismissed") == 1 and len(statuses) == 3


@pytest.mark.slow
async def test_resaved_copy_from_case_documents_has_no_differences(
    client: httpx.AsyncClient, lab: Lab
) -> None:
    body = await upload(
        client,
        lab.acct,
        lab.case_id,
        [("test_resaved.pdf", (ROOT / "test_resaved.pdf").read_bytes())],
    )
    assert (await run_job(lab.acct, body["job_id"])).value == "succeeded"
    resaved = body["results"][0]["document_id"]
    resp = await client.post(
        f"/api/v1/cases/{lab.case_id}/comparisons",
        headers=lab.acct.headers,
        json={"original_document_id": lab.original_id, "test_document_id": resaved},
    )
    assert resp.status_code == 202, resp.text
    cid = resp.json()["id"]
    assert (
        await run_comparison(lab.acct.organization_id, uuid.UUID(cid), get_store(), no_vision)
        == "completed"
    )
    d = (await client.get(f"/api/v1/comparisons/{cid}", headers=lab.acct.headers)).json()
    assert d["findings"] == [] and d["vlm_status"] == "disabled"
    # Running again changes nothing (the task is idempotent).
    assert (
        await run_comparison(lab.acct.organization_id, uuid.UUID(cid), get_store(), no_vision)
        == "completed"
    )


@pytest.mark.slow
async def test_invalid_requests_are_refused(client: httpx.AsyncClient, lab: Lab) -> None:
    url = f"/api/v1/cases/{lab.case_id}/comparisons"
    same = await client.post(
        url,
        headers=lab.acct.headers,
        json={"original_document_id": lab.test_id, "test_document_id": lab.test_id},
    )
    assert same.status_code == 422
    other_case = await new_case(client, lab.acct, title="Other")
    moved = await client.post(
        f"/api/v1/cases/{other_case['id']}/comparisons",
        headers=lab.acct.headers,
        json={"original_document_id": lab.original_id, "test_document_id": lab.test_id},
    )
    assert moved.status_code == 404
    csv = await upload(client, lab.acct, lab.case_id, [("rows.csv", b"amount,currency\n1,USD\n")])
    csv_id = csv["results"][0]["document_id"]
    refused = await client.post(
        url,
        headers=lab.acct.headers,
        json={"original_document_id": lab.original_id, "test_document_id": csv_id},
    )
    assert refused.status_code == 422 and "compared visually" in refused.json()["detail"]
    identical = await _upload_pair(
        client, lab.acct, lab.case_id, "original_invoice.pdf", "original_invoice.pdf"
    )
    assert identical.status_code == 409
    not_failed = await client.post(
        f"/api/v1/comparisons/{lab.comparison_id}/retry", headers=lab.acct.headers
    )
    assert not_failed.status_code == 409


@pytest.mark.slow
async def test_a_failed_document_fails_the_comparison_and_retry_requeues_it(
    client: httpx.AsyncClient, lab: Lab
) -> None:
    broken = await upload(
        client, lab.acct, lab.case_id, [("broken.pdf", b"%PDF-1.7\n1 0 obj <<>> endobj\n%%EOF")]
    )
    result = broken["results"][0]
    if result["status"] != "accepted":
        pytest.fail(f"the broken PDF was not accepted for processing: {result}")
    await run_job(lab.acct, broken["job_id"])
    resp = await client.post(
        f"/api/v1/cases/{lab.case_id}/comparisons",
        headers=lab.acct.headers,
        json={"original_document_id": lab.original_id, "test_document_id": result["document_id"]},
    )
    cid = resp.json()["id"]
    assert (
        await run_comparison(lab.acct.organization_id, uuid.UUID(cid), get_store(), no_vision)
        == "failed"
    )
    d = (await client.get(f"/api/v1/comparisons/{cid}", headers=lab.acct.headers)).json()
    assert d["status"] == "failed" and "broken.pdf" in d["error"]
    retried = await client.post(f"/api/v1/comparisons/{cid}/retry", headers=lab.acct.headers)
    assert retried.status_code == 202 and retried.json()["status"] == "queued"
    export = await client.post(
        f"/api/v1/comparisons/{cid}/exports",
        headers=lab.acct.headers,
        json={"kind": "findings_json"},
    )
    assert export.status_code == 409


@pytest.mark.slow
async def test_comparisons_are_isolated_between_organizations(
    client: httpx.AsyncClient, lab: Lab
) -> None:
    outsider = await register(client, org_name="Comparison Outsider")
    d = await _detail(client, lab)
    fid = d["findings"][0]["id"]
    eid = d["exports"][0]["id"]
    cid = lab.comparison_id
    h = outsider.headers
    checks = [
        ("GET", f"/api/v1/cases/{lab.case_id}/comparisons", None),
        (
            "POST",
            f"/api/v1/cases/{lab.case_id}/comparisons",
            {"original_document_id": lab.original_id, "test_document_id": lab.test_id},
        ),
        ("GET", f"/api/v1/comparisons/{cid}", None),
        ("POST", f"/api/v1/comparisons/{cid}/retry", None),
        (
            "PATCH",
            f"/api/v1/comparisons/{cid}/findings/{fid}/review",
            {"status": "needs_more_evidence"},
        ),
        ("GET", f"/api/v1/comparisons/{cid}/findings/{fid}/reviews", None),
        ("POST", f"/api/v1/comparisons/{cid}/exports", {"kind": "findings_json"}),
        ("GET", f"/api/v1/comparisons/{cid}/exports", None),
        ("GET", f"/api/v1/comparison-exports/{eid}/download", None),
        ("GET", f"/api/v1/comparisons/{uuid.uuid4()}", None),
    ]
    for method, path, body in checks:
        resp = await client.request(method, path, headers=h, json=body)
        assert resp.status_code == 404, f"{method} {path}: {resp.status_code}"
    upload_resp = await client.post(
        f"/api/v1/cases/{lab.case_id}/comparisons/upload",
        headers=h,
        files=_files("original_invoice.pdf", "test_altered.pdf"),
    )
    assert upload_resp.status_code == 404
    # A finding id of this organization under another comparison id is also a 404.
    own_other = await client.get(
        f"/api/v1/comparisons/{uuid.uuid4()}/findings/{fid}/reviews", headers=lab.acct.headers
    )
    assert own_other.status_code == 404
    for table in TABLES:
        async with session_scope() as s:
            await set_tenant(s, outsider.organization_id)
            seen = (await s.scalars(text(f"SELECT organization_id FROM {table}"))).all()  # noqa: S608
        assert seen == [], table
        async with session_scope() as s:
            unscoped = (await s.scalars(text(f"SELECT organization_id FROM {table}"))).all()  # noqa: S608
        assert unscoped == [], f"{table} visible without tenant context"
        async with session_scope() as s:
            await set_tenant(s, lab.acct.organization_id)
            own = set((await s.scalars(text(f"SELECT organization_id FROM {table}"))).all())  # noqa: S608
        assert own == {lab.acct.organization_id}, table


@pytest.mark.slow
async def test_a_scanned_altered_copy_is_aligned_and_compared_through_ocr(
    client: httpx.AsyncClient, lab: Lab
) -> None:
    resp = await _upload_pair(
        client, lab.acct, lab.case_id, "original_invoice.pdf", "test_scanned_altered.png"
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["original"]["status"] == "duplicate"  # the original is reused, not stored twice
    assert (await run_job(lab.acct, body["job_id"])).value == "succeeded"
    cid = body["comparison"]["id"]
    assert (
        await run_comparison(lab.acct.organization_id, uuid.UUID(cid), get_store(), no_vision)
        == "completed"
    )
    d = (await client.get(f"/api/v1/comparisons/{cid}", headers=lab.acct.headers)).json()
    [page] = d["summary"]["pages"]
    assert page["alignment"] != "identity" and page["page_ssim"] > 0.9
    assert page["test_text_method"] == "ocr"
    boxes = MANIFEST["scan"]["boxes_px"]
    for key in ("total", "date"):
        hits = [
            f for f in d["findings"] if f["test_page"] == 1 and overlaps(f["region"], boxes[key])
        ]
        assert hits, key
        assert hits[0]["test_text"] in MANIFEST["changes"][key]["test"]
    assert [f["original_page"] for f in d["findings"] if f["type"] == "page_removed"] == [2]
    assert len(d["findings"]) == 3, [f["explanation"] for f in d["findings"]]
