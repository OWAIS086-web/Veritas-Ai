# Req: document-ingestion 1.x, 2.x, 3.x, 4.x
from __future__ import annotations

import io
import json
import uuid
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.core.signing import sign
from app.integrations.storage.base import ObjectExistsError, original_key
from app.integrations.storage.s3_store import get_store
from tests.integration.conftest import Account, register

pytestmark = pytest.mark.integration
SAMPLES = Path(__file__).resolve().parents[3] / "sample-data"
CASE_PDFS = sorted((SAMPLES / "shipment-case").glob("*.pdf"))
PDF = (SAMPLES / "shipment-case" / "02_commercial_invoice.pdf").read_bytes()


async def new_case(
    client: httpx.AsyncClient, acct: Account, title: str = "Shipment SHIP-2049", **extra: Any
) -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/cases",
        headers=acct.headers,
        json={"title": title, "objective": "Reconcile declared values", **extra},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def upload(
    client: httpx.AsyncClient, acct: Account, case_id: str, files: list[tuple[str, bytes]]
) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/cases/{case_id}/documents",
        headers=acct.headers,
        files=[("files", (name, data, "application/octet-stream")) for name, data in files],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


async def test_case_crud_filters_and_soft_delete(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    a = await new_case(client, acct, "Alpha shipment", priority="high")
    await new_case(client, acct, "Beta claim", investigation_type="insurance_claim")
    listed = (await client.get("/api/v1/cases", headers=acct.headers)).json()
    assert [c["title"] for c in listed["items"]] == ["Beta claim", "Alpha shipment"]
    high = (await client.get("/api/v1/cases?priority=high", headers=acct.headers)).json()
    assert [c["title"] for c in high["items"]] == ["Alpha shipment"]
    search = (await client.get("/api/v1/cases?q=claim", headers=acct.headers)).json()
    assert [c["title"] for c in search["items"]] == ["Beta claim"]
    wild = (await client.get("/api/v1/cases?q=%25", headers=acct.headers)).json()
    assert wild["items"] == []  # "%" is matched literally, not as a wildcard
    patched = await client.patch(
        f"/api/v1/cases/{a['id']}", headers=acct.headers, json={"status": "closed"}
    )
    assert patched.json()["status"] == "closed"
    assert (
        await client.delete(f"/api/v1/cases/{a['id']}", headers=acct.headers)
    ).status_code == 204
    assert (await client.get(f"/api/v1/cases/{a['id']}", headers=acct.headers)).status_code == 404
    titles = [
        c["title"]
        for c in (await client.get("/api/v1/cases", headers=acct.headers)).json()["items"]
    ]
    assert titles == ["Beta claim"]


async def test_case_pagination(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    for i in range(5):
        await new_case(client, acct, f"Case number {i}")
    p1 = (await client.get("/api/v1/cases?limit=2", headers=acct.headers)).json()
    p2 = (
        await client.get(f"/api/v1/cases?limit=2&cursor={p1['next_cursor']}", headers=acct.headers)
    ).json()
    p3 = (
        await client.get(f"/api/v1/cases?limit=2&cursor={p2['next_cursor']}", headers=acct.headers)
    ).json()
    ids = [c["id"] for p in (p1, p2, p3) for c in p["items"]]
    assert len(ids) == len(set(ids)) == 5 and p3["next_cursor"] is None
    # A malformed cursor is an error, never silently treated as "first page".
    bad = await client.get("/api/v1/cases?cursor=not-a-cursor", headers=acct.headers)
    assert bad.status_code == 422


async def test_upload_accepts_hashes_stores_and_queues(
    client: httpx.AsyncClient, no_broker: list[tuple[uuid.UUID, uuid.UUID]]
) -> None:
    acct = await register(client)
    case = await new_case(client, acct)
    body = await upload(client, acct, case["id"], [(p.name, p.read_bytes()) for p in CASE_PDFS])
    assert [r["status"] for r in body["results"]] == ["accepted"] * 7
    assert body["job_id"] and no_broker == [(acct.organization_id, uuid.UUID(body["job_id"]))]
    docs = (await client.get(f"/api/v1/cases/{case['id']}/documents", headers=acct.headers)).json()
    manifest = json.loads((SAMPLES / "manifest.json").read_text())["files"]
    for doc in docs:
        assert doc["status"] == "uploaded" and doc["mime_type"] == "application/pdf"
        assert doc["sha256"] == manifest[f"shipment-case/{doc['original_filename']}"]["sha256"]
        stored = await get_store().get(original_key(acct.organization_id, uuid.UUID(doc["id"])))
        assert stored == (SAMPLES / "shipment-case" / doc["original_filename"]).read_bytes()
    job = (await client.get(f"/api/v1/jobs/{body['job_id']}", headers=acct.headers)).json()
    assert job["status"] == "queued"
    logs = (await client.get("/api/v1/audit-logs?limit=100", headers=acct.headers)).json()["items"]
    assert sum(e["action"] == "document.upload" for e in logs) == 7


async def test_originals_are_never_overwritten(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    case = await new_case(client, acct)
    body = await upload(client, acct, case["id"], [("invoice.pdf", PDF)])
    key = original_key(acct.organization_id, uuid.UUID(body["results"][0]["document_id"]))
    with pytest.raises(ObjectExistsError):
        await get_store().put_new(key, b"%PDF-tampered", "application/pdf")
    with pytest.raises(ValueError):
        await get_store().put_derived(key, b"x", "application/pdf")
    assert await get_store().get(key) == PDF


async def test_duplicates_versions_and_rejections(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    case = await new_case(client, acct)
    first = await upload(client, acct, case["id"], [("invoice.pdf", PDF), ("copy.pdf", PDF)])
    assert [r["status"] for r in first["results"]] == ["accepted", "duplicate"]
    again = await upload(client, acct, case["id"], [("renamed.pdf", PDF)])
    assert again["results"][0]["status"] == "duplicate"
    assert again["results"][0]["document_id"] == first["results"][0]["document_id"]
    assert again["job_id"] is None
    other = (SAMPLES / "shipment-case" / "01_purchase_order.pdf").read_bytes()
    version = await upload(client, acct, case["id"], [("invoice.pdf", other)])
    new_id = version["results"][0]["document_id"]
    doc = (await client.get(f"/api/v1/documents/{new_id}", headers=acct.headers)).json()
    assert doc["supersedes_id"] == first["results"][0]["document_id"]

    bad = await upload(
        client,
        acct,
        case["id"],
        [
            ("evil.pdf", b"MZ\x90\x00" + b"\x00" * 200),
            ("notes.txt", b"just some prose without structure"),
            ("traversal.zip", _zip({"../../etc/passwd.pdf": PDF})),
            ("nested.zip", _zip({"inner.zip": _zip({"a.pdf": PDF})})),
        ],
    )
    reasons = [r["reason"] for r in bad["results"]]
    assert [r["status"] for r in bad["results"]] == ["rejected"] * 4
    assert reasons[0].startswith("unsupported_type") and reasons[1].startswith("unsupported_type")
    assert reasons[2:] == ["unsafe_entry_path", "nested_archive"]


async def test_zip_entries_are_ingested_individually(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    case = await new_case(client, acct)
    archive = _zip({f"pkg/{p.name}": p.read_bytes() for p in CASE_PDFS[:3]})
    body = await upload(client, acct, case["id"], [("package.zip", archive)])
    assert [r["status"] for r in body["results"]] == ["accepted"] * 3
    docs = (await client.get(f"/api/v1/cases/{case['id']}/documents", headers=acct.headers)).json()
    assert {d["source_archive"] for d in docs} == {"package.zip"}
    assert sorted(d["original_filename"] for d in docs) == sorted(p.name for p in CASE_PDFS[:3])


async def test_oversize_file_is_rejected(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    acct = await register(client)
    case = await new_case(client, acct)
    body = await upload(client, acct, case["id"], [("big.pdf", PDF + b"0" * (1024 * 1024))])
    assert body["results"][0] == {
        "filename": "big.pdf",
        "status": "rejected",
        "document_id": None,
        "reason": "too_large",
        "detected_type": None,
    }


async def test_filenames_are_metadata_only(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    case = await new_case(client, acct)
    body = await upload(client, acct, case["id"], [("..\\..\\<script>x.pdf", PDF)])
    doc_id = body["results"][0]["document_id"]
    doc = (await client.get(f"/api/v1/documents/{doc_id}", headers=acct.headers)).json()
    assert doc["original_filename"] == "script>x.pdf".replace(">", "")
    assert await get_store().exists(original_key(acct.organization_id, uuid.UUID(doc_id)))


async def test_signed_preview_serves_bytes_and_expires(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    case = await new_case(client, acct)
    doc_id = (await upload(client, acct, case["id"], [("invoice.pdf", PDF)]))["results"][0][
        "document_id"
    ]
    preview = (await client.get(f"/api/v1/documents/{doc_id}/preview", headers=acct.headers)).json()
    served = await client.get(preview["url"])
    assert served.status_code == 200 and served.content == PDF
    assert served.headers["content-type"] == "application/pdf"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in served.headers["content-security-policy"]
    assert served.headers["content-disposition"] == 'inline; filename="invoice.pdf"'
    # Regression: download managers (IDM) captured the viewer's PDF and the page got a 204.
    # The viewer's marked request gets the same bytes as an anonymous binary stream.
    viewed = await client.get(preview["url"], headers={"X-Veritas-Viewer": "1"})
    assert viewed.status_code == 200 and viewed.content == PDF
    assert viewed.headers["content-type"] == "application/octet-stream"
    assert viewed.headers["content-disposition"] == "inline"
    assert viewed.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in viewed.headers["content-security-policy"]
    token = preview["url"].rsplit("/", 1)[1]
    assert (await client.get(f"/api/v1/files/{token[:-2]}xx")).status_code == 403
    expired, _ = sign(uuid.UUID(doc_id), acct.organization_id, -5)
    assert (await client.get(f"/api/v1/files/{expired}")).status_code == 403
    other_org, _ = sign(uuid.UUID(doc_id), uuid.uuid4(), 60)
    assert (await client.get(f"/api/v1/files/{other_org}")).status_code == 404
    logs = (await client.get("/api/v1/audit-logs", headers=acct.headers)).json()["items"]
    actions = {e["action"] for e in logs}
    assert {"document.access", "document.download"} <= actions


async def test_everything_is_404_across_organizations(client: httpx.AsyncClient) -> None:
    owner = await register(client)
    intruder = await register(client)
    case = await new_case(client, owner)
    doc_id = (await upload(client, owner, case["id"], [("invoice.pdf", PDF)]))["results"][0][
        "document_id"
    ]
    paths = [
        ("GET", f"/api/v1/cases/{case['id']}"),
        ("PATCH", f"/api/v1/cases/{case['id']}"),
        ("DELETE", f"/api/v1/cases/{case['id']}"),
        ("GET", f"/api/v1/cases/{case['id']}/documents"),
        ("POST", f"/api/v1/cases/{case['id']}/process"),
        ("GET", f"/api/v1/documents/{doc_id}"),
        ("GET", f"/api/v1/documents/{doc_id}/pages"),
        ("GET", f"/api/v1/documents/{doc_id}/extractions"),
        ("GET", f"/api/v1/documents/{doc_id}/preview"),
        ("POST", f"/api/v1/documents/{doc_id}/retry"),
    ]
    for method, path in paths:
        resp = await client.request(
            method,
            path,
            headers=intruder.headers,
            json={"title": "x-y-z"} if method == "PATCH" else None,
        )
        assert resp.status_code == 404, (method, path, resp.status_code)
    up = await client.post(
        f"/api/v1/cases/{case['id']}/documents",
        headers=intruder.headers,
        files=[("files", ("a.pdf", PDF, "application/pdf"))],
    )
    assert up.status_code == 404
    listed = (await client.get("/api/v1/documents", headers=intruder.headers)).json()
    assert listed["items"] == []


async def test_roles_without_upload_permission_are_refused(client: httpx.AsyncClient) -> None:
    from tests.integration.conftest import login

    admin = await register(client)
    reviewer = await register(client)
    await client.post(
        f"/api/v1/organizations/{admin.organization_id}/members",
        headers=admin.headers,
        json={"email": reviewer.email, "role": "reviewer"},
    )
    session = await login(client, reviewer, organization_id=admin.organization_id)
    case = await new_case(client, admin)
    resp = await client.post(
        f"/api/v1/cases/{case['id']}/documents",
        headers=session.headers,
        files=[("files", ("a.pdf", PDF, "application/pdf"))],
    )
    assert resp.status_code == 403
    assert (
        await client.post("/api/v1/cases", headers=session.headers, json={"title": "Not allowed"})
    ).status_code == 403
    assert (
        await client.get(f"/api/v1/cases/{case['id']}", headers=session.headers)
    ).status_code == 200


@settings(
    max_examples=8, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(payload=st.binary(min_size=1, max_size=64), copies=st.integers(min_value=2, max_value=4))
async def test_identical_bytes_are_stored_once_per_case(
    client: httpx.AsyncClient, payload: bytes, copies: int
) -> None:
    acct = await register(client)
    case = await new_case(client, acct)
    data = b"%PDF-1.7\n" + payload
    body = await upload(client, acct, case["id"], [(f"f{i}.pdf", data) for i in range(copies)])
    statuses = [r["status"] for r in body["results"]]
    assert statuses == ["accepted"] + ["duplicate"] * (copies - 1)
    assert len({r["document_id"] for r in body["results"]}) == 1
