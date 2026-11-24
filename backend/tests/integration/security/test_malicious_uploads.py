# Req: enterprise-security 2.1, 2.2
"""Malicious upload fixtures through the real API, processing and storage. Each one is
rejected with a recorded reason, or accepted as exactly one harmless interpretation."""

from __future__ import annotations

import io
import uuid
import zipfile
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import tenant_session
from app.integrations.storage.s3_store import get_store
from app.models import Document, DocumentPage
from tests.integration.conftest import Account, register
from tests.integration.test_cases_and_upload import new_case, upload
from tests.integration.test_pipeline import run_job

pytestmark = pytest.mark.integration
SAMPLES = Path(__file__).resolve().parents[4] / "sample-data" / "shipment-case"
EXE = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 56 + b"This program cannot be run in DOS mode."


def _zip(entries: dict[str, bytes], method: int = zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", method) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _pdf() -> bytes:
    return (SAMPLES / "02_commercial_invoice.pdf").read_bytes()


def _eml_with_executable() -> bytes:
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = "supplier@example.com"
    msg["To"] = "buyer@example.com"
    msg["Subject"] = "Invoice CMP-INV-3001 (SYNTHETIC DEMONSTRATION DATA)"
    msg.set_content("Please find the invoice attached.")
    msg.add_attachment(EXE, maintype="application", subtype="octet-stream", filename="invoice.exe")
    return msg.as_bytes()


async def _one(client: httpx.AsyncClient, acct: Account, case_id: str, name: str, data: bytes):  # type: ignore[no-untyped-def]
    body = await upload(client, acct, case_id, [(name, data)])
    return body, body["results"]


@pytest.fixture
async def owner(client: httpx.AsyncClient) -> tuple[Account, str]:
    acct = await register(client, org_name="Upload Safety Org")
    case = await new_case(client, acct, title="Malicious uploads")
    return acct, case["id"]


@pytest.mark.parametrize(
    ("name", "data", "reason"),
    [
        ("invoice.pdf", EXE, "unsupported"),  # an executable with a document extension
        # 20 MB of one byte deflates about 1000:1 (the limit is 100:1); it stays under the
        # 25 MB entry limit, so the ratio check is what rejects it.
        (
            "zip-bomb.zip",
            _zip({"zeros.pdf": b"%PDF-1.7\n" + b"0" * 20_000_000}),
            "compression_ratio_exceeded",
        ),
        ("traversal.zip", _zip({"../../etc/evil.pdf": b"%PDF-1.7\n%%EOF"}), "unsafe_entry_path"),
        ("absolute.zip", _zip({"/var/evil.pdf": b"%PDF-1.7\n%%EOF"}), "unsafe_entry_path"),
        ("drive.zip", _zip({"C:/evil.pdf": b"%PDF-1.7\n%%EOF"}), "unsafe_entry_path"),
        ("nested.zip", _zip({"inner.zip": _zip({"a.pdf": b"%PDF-1.7\n%%EOF"})}), "nested_archive"),
        # Rejected by type detection before expansion is attempted.
        ("broken.zip", b"PK\x03\x04" + b"\x00" * 40, "unreadable archive"),
        ("empty.pdf", b"", "empty"),
    ],
)
async def test_malicious_files_are_rejected_with_a_reason_and_nothing_is_stored(
    client: httpx.AsyncClient, owner: tuple[Account, str], name: str, data: bytes, reason: str
) -> None:
    acct, case_id = owner
    body, [result] = await _one(client, acct, case_id, name, data)
    assert result["status"] == "rejected", result
    assert reason in (result["reason"] or ""), result
    assert body["job_id"] is None
    async with tenant_session(acct.organization_id) as s:
        stored = (
            await s.scalars(select(Document.id).where(Document.case_id == uuid.UUID(case_id)))
        ).all()
    assert stored == []


async def test_an_oversized_file_is_refused_before_it_is_read_in_full(
    client: httpx.AsyncClient, owner: tuple[Account, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    acct, case_id = owner
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    _, [result] = await _one(
        client, acct, case_id, "big.pdf", b"%PDF-1.7\n" + b"0" * (1024 * 1024 + 10)
    )
    assert (result["status"], result["reason"]) == ("rejected", "too_large")


async def test_a_pdf_zip_polyglot_has_exactly_one_interpretation(
    client: httpx.AsyncClient, owner: tuple[Account, str]
) -> None:
    """A real PDF with a ZIP appended: detected from its first bytes as one PDF; the ZIP part
    is never expanded, so no hidden entry becomes a document."""
    acct, case_id = owner
    polyglot = _pdf() + _zip({"hidden.pdf": _pdf(), "payload.exe": EXE})
    body, results = await _one(client, acct, case_id, "invoice.zip", polyglot)
    assert len(results) == 1 and results[0]["status"] == "accepted"
    assert results[0]["detected_type"] == "application/pdf"
    assert (await run_job(acct, body["job_id"])).value == "succeeded"
    async with tenant_session(acct.organization_id) as s:
        docs = (
            await s.scalars(select(Document).where(Document.case_id == uuid.UUID(case_id)))
        ).all()
    assert [d.mime_type for d in docs] == ["application/pdf"]
    assert docs[0].original_filename == "invoice.zip"  # the name is metadata only


async def test_an_email_attachment_is_never_executed_parsed_or_served(
    client: httpx.AsyncClient, owner: tuple[Account, str]
) -> None:
    acct, case_id = owner
    body, [result] = await _one(client, acct, case_id, "invoice.eml", _eml_with_executable())
    assert result["status"] == "accepted" and result["detected_type"] == "message/rfc822"
    assert (await run_job(acct, body["job_id"])).value == "succeeded"
    doc_id = uuid.UUID(result["document_id"])
    async with tenant_session(acct.organization_id) as s:
        doc = await s.get(Document, doc_id)
        pages = (
            await s.scalars(select(DocumentPage).where(DocumentPage.document_id == doc_id))
        ).all()
    assert doc is not None and doc.status == "completed"
    text = " ".join(p.text for p in pages)
    assert "Please find the invoice attached." in text
    assert "This program cannot be run" not in text  # attachment bytes were not parsed
    stage = (await client.get(f"/api/v1/documents/{doc_id}", headers=acct.headers)).json()
    parse = next(s for s in stage["stages"] if s["stage"] == "parse")
    assert parse["status"] == "succeeded"
    # The only stored object is the uploaded message itself; no attachment is stored apart.
    assert await get_store().exists(doc.storage_key)
    assert doc.storage_key.endswith("/original")


async def test_downloads_are_attachments_with_safe_names_and_no_sniffing(
    client: httpx.AsyncClient, owner: tuple[Account, str]
) -> None:
    acct, case_id = owner
    evil = 'inv"oice<script>\r\nX-Injected: 1.pdf'
    _, [result] = await _one(client, acct, case_id, evil, _pdf())
    assert result["status"] == "accepted"
    preview = await client.get(
        f"/api/v1/documents/{result['document_id']}/preview", headers=acct.headers
    )
    url = preview.json()["url"]
    direct = await client.get(url)
    assert direct.status_code == 200
    disposition = direct.headers["content-disposition"]
    assert disposition.startswith("attachment; filename=")
    assert '"' not in disposition[len('attachment; filename="') : -1]
    assert "<" not in disposition and "\r" not in disposition and "\n" not in disposition
    assert "x-injected" not in {k.lower() for k in direct.headers}
    assert direct.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in direct.headers["content-security-policy"]
    # The in-app viewer gets an anonymous binary body; an <img> tag renders inline.
    viewer = await client.get(url, headers={"X-Veritas-Viewer": "1"})
    assert viewer.headers["content-type"] == "application/octet-stream"
    assert viewer.headers["content-disposition"] == "inline"
    as_image = await client.get(url, headers={"Sec-Fetch-Dest": "image"})
    assert as_image.headers["content-disposition"].startswith("attachment")  # a PDF, not an image
