# Req: document-intelligence 1.x, 3.x, 4.x, 5.x, 6.1
"""The real pipeline (PyMuPDF, Docling, OpenCV, PaddleOCR, rules extraction) on the sample
package, persisted in Postgres, with idempotency, failure and retry behaviour."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.core.db import tenant_session
from app.integrations.storage.s3_store import get_store
from app.models import DocumentPage, DocumentStage, ExtractedField, Job, JobEvent
from app.services.jobs.runner import Outcome, execute_streaming_job
from app.workflows import document_pipeline
from tests.integration.conftest import Account, register
from tests.integration.test_cases_and_upload import new_case, upload

pytestmark = pytest.mark.integration
SAMPLES = Path(__file__).resolve().parents[3] / "sample-data"
MANIFEST = json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))["files"]


async def run_job(acct: Account, job_id: str) -> Outcome:
    async def work(payload: dict[str, Any], emit: Any) -> dict[str, Any]:
        return await document_pipeline.process_batch(
            acct.organization_id, payload, emit, get_store()
        )

    return (await execute_streaming_job(acct.organization_id, uuid.UUID(job_id), work)).outcome


async def fields_of(client: httpx.AsyncClient, acct: Account, doc_id: str) -> dict[str, Any]:
    ext = (await client.get(f"/api/v1/documents/{doc_id}/extractions", headers=acct.headers)).json()
    return {f["name"]: f for f in ext["fields"]}


@pytest.fixture(scope="module")
def shipment_files() -> list[tuple[str, bytes]]:
    return [(p.name, p.read_bytes()) for p in sorted((SAMPLES / "shipment-case").glob("*.pdf"))]


@pytest.mark.slow
async def test_seven_document_case_processes_to_ground_truth(
    client: httpx.AsyncClient, shipment_files: list[tuple[str, bytes]]
) -> None:
    acct = await register(client)
    case = await new_case(client, acct)
    body = await upload(client, acct, case["id"], shipment_files)
    assert await run_job(acct, body["job_id"]) is Outcome.SUCCEEDED

    job = (await client.get(f"/api/v1/jobs/{body['job_id']}", headers=acct.headers)).json()
    assert job["status"] == "succeeded" and job["result"]["completed"] == 7
    docs = (await client.get(f"/api/v1/cases/{case['id']}/documents", headers=acct.headers)).json()
    totals: dict[str, tuple[str, str, int]] = {}
    for doc in docs:
        truth = MANIFEST[f"shipment-case/{doc['original_filename']}"]
        assert doc["status"] == "completed", doc["error"]
        assert doc["doc_type"] == truth["doc_type"]
        assert doc["language"] == "en" and doc["page_count"] >= 1
        assert [s["stage"] for s in doc["stages"]] == list(document_pipeline.STAGES)
        assert document_pipeline.STAGES[-1] == "forensics"
        assert all(s["status"] == "succeeded" for s in doc["stages"])
        fields = await fields_of(client, acct, doc["id"])
        assert fields["document_number"]["value"] == truth["document_number"]
        if "total_amount" in truth:
            total = fields["total_amount"]
            assert total["status"] == "extracted" and total["page_number"] == truth["total_page"]
            assert total["normalized_value"] == {"amount": truth["total_amount"], "currency": "USD"}
            assert len(total["bbox"]) == 4 and total["confidence"] == "1.000"
            assert total["method"] == "text_layer" and total["model_version"].startswith("rules")
            totals[doc["doc_type"]] = (
                total["normalized_value"]["amount"],
                total["currency"],
                total["page_number"],
            )
        if "total_quantity" in truth:
            assert fields["total_quantity"]["normalized_value"]["quantity"] == "1000"
    # The demo's raw material: three documents at 48,000 and two at 68,000, all USD.
    assert sorted(v[0] for v in totals.values()) == ["48000.00"] * 3 + ["68000.00"] * 2
    assert totals["customs_declaration"][2] == 2

    pages = (
        await client.get(f"/api/v1/documents/{docs[0]['id']}/pages", headers=acct.headers)
    ).json()
    assert pages[0]["coord_unit"] == "pt" and pages[0]["method"] == "text_layer"
    assert pages[0]["lines"][0]["tokens"][0]["bbox"]
    invoice = next(d for d in docs if d["doc_type"] == "commercial_invoice")
    parse_metrics = next(s for s in invoice["stages"] if s["stage"] == "parse")["metrics"]
    assert parse_metrics["layout"]["status"] == "ok" and parse_metrics["layout"]["tables"] >= 1

    async with tenant_session(acct.organization_id) as s:
        events = list(
            await s.scalars(
                select(JobEvent.type)
                .where(JobEvent.job_id == uuid.UUID(body["job_id"]))
                .order_by(JobEvent.seq)
            )
        )
    assert events[0] == "queued" and events[-1] == "succeeded"
    assert events.count("document_completed") == 7 and events.count("stage_completed") == 35

    stats = (await client.get("/api/v1/stats/overview", headers=acct.headers)).json()
    assert stats["documents_processed"]["value"] == 7
    assert stats["active_investigations"]["value"] == 1


@pytest.mark.slow
@pytest.mark.parametrize(
    ("filename", "method", "field", "expected"),
    [
        (
            "commercial_invoice_scanned.pdf",
            "ocr",
            "total_amount",
            {"amount": "48000.00", "currency": "USD"},
        ),
        ("purchase_order.png", "ocr", "total_amount", {"amount": "48000.00", "currency": "USD"}),
        ("payment_receipt.jpg", "ocr", "total_amount", {"amount": "48000.00", "currency": "USD"}),
        ("bill_of_lading.tiff", "ocr", "total_quantity", {"quantity": "1000", "unit": "units"}),
        (
            "commercial_invoice.docx",
            "parser",
            "total_amount",
            {"amount": "48000.00", "currency": "USD"},
        ),
        ("packing_list.xlsx", "parser", "total_quantity", {"quantity": "1000", "unit": "units"}),
        (
            "commercial_invoice.csv",
            "parser",
            "total_amount",
            {"amount": "48000.00", "currency": "USD"},
        ),
        ("payment_advice.eml", "parser", "total_amount", {"amount": "48000.00", "currency": "USD"}),
    ],
)
async def test_every_format_variant_processes(
    client: httpx.AsyncClient, filename: str, method: str, field: str, expected: dict[str, str]
) -> None:
    acct = await register(client)
    case = await new_case(client, acct)
    data = (SAMPLES / "format-variants" / filename).read_bytes()
    body = await upload(client, acct, case["id"], [(filename, data)])
    assert await run_job(acct, body["job_id"]) is Outcome.SUCCEEDED
    doc_id = body["results"][0]["document_id"]
    doc = (await client.get(f"/api/v1/documents/{doc_id}", headers=acct.headers)).json()
    truth = MANIFEST[f"format-variants/{filename}"]
    assert doc["status"] == "completed", doc["error"]
    assert doc["doc_type"] == truth["doc_type"]
    value = (await fields_of(client, acct, doc_id))[field]
    assert value["status"] == "extracted", value["rejection_reason"]
    assert value["normalized_value"] == expected and value["method"] == method
    if method == "ocr":
        assert value["bbox"] and value["confidence"] is not None
        assert 0 < float(value["confidence"]) <= 1  # PaddleOCR's own score
        assert "paddleocr" in value["model_version"]
    else:
        assert value["bbox"] is None and value["location"]
    if filename.endswith(".tiff"):
        # Browsers can't show TIFF, so each frame has a derived PNG; the original is unchanged.
        preview = (
            await client.get(f"/api/v1/documents/{doc_id}/preview?page=1", headers=acct.headers)
        ).json()
        image = await client.get(preview["url"])
        assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
        assert preview["mime_type"] == "image/png"
        original = (
            await client.get(f"/api/v1/documents/{doc_id}/preview", headers=acct.headers)
        ).json()
        assert (await client.get(original["url"])).content == data
        missing = await client.get(
            f"/api/v1/documents/{doc_id}/preview?page=9", headers=acct.headers
        )
        assert missing.status_code == 404


@pytest.mark.slow
async def test_rerunning_stages_creates_no_duplicates(
    client: httpx.AsyncClient, shipment_files: list[tuple[str, bytes]]
) -> None:
    acct = await register(client)
    case = await new_case(client, acct)
    body = await upload(client, acct, case["id"], shipment_files[:1])
    doc_id = uuid.UUID(body["results"][0]["document_id"])
    await run_job(acct, body["job_id"])

    async def counts() -> tuple[int, int, int]:
        async with tenant_session(acct.organization_id) as s:
            pages = await s.scalar(
                select(func.count())
                .select_from(DocumentPage)
                .where(DocumentPage.document_id == doc_id)
            )
            fields = await s.scalar(
                select(func.count())
                .select_from(ExtractedField)
                .where(ExtractedField.document_id == doc_id)
            )
            attempts = await s.scalar(
                select(func.sum(DocumentStage.attempts)).where(DocumentStage.document_id == doc_id)
            )
        return int(pages or 0), int(fields or 0), int(attempts or 0)

    before = await counts()
    # A completed document is skipped entirely (e.g. a redelivered Celery task).
    assert (
        await document_pipeline.process_document(acct.organization_id, doc_id, get_store())
        == "completed"
    )
    assert await counts() == before
    # Forcing every stage to run again replaces their rows instead of adding to them.
    async with tenant_session(acct.organization_id) as s:
        for row in await s.scalars(
            select(DocumentStage).where(DocumentStage.document_id == doc_id)
        ):
            row.status = "pending"
    await document_pipeline.process_document(acct.organization_id, doc_id, get_store())
    after = await counts()
    assert after[:2] == before[:2] and after[2] == before[2] + 5


async def test_failing_stage_retries_then_fails_and_retry_resumes(
    client: httpx.AsyncClient,
    shipment_files: list[tuple[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    acct = await register(client)
    case = await new_case(client, acct)
    body = await upload(client, acct, case["id"], shipment_files[1:2])
    doc_id = body["results"][0]["document_id"]
    real_make = document_pipeline.make_stages
    calls = {"extract": 0}

    def broken(store: Any) -> Any:
        stages = real_make(store)

        async def explode(org: uuid.UUID, doc: Any) -> dict[str, Any]:
            calls["extract"] += 1
            raise RuntimeError("simulated extractor crash")

        return {**stages, "extract": explode}

    monkeypatch.setattr(document_pipeline, "make_stages", broken)
    monkeypatch.setattr(document_pipeline.asyncio, "sleep", _no_sleep)
    assert await run_job(acct, body["job_id"]) is Outcome.SUCCEEDED  # the batch itself ran
    doc = (await client.get(f"/api/v1/documents/{doc_id}", headers=acct.headers)).json()
    assert doc["status"] == "failed" and "simulated extractor crash" in doc["error"]
    stages = {s["stage"]: s for s in doc["stages"]}
    assert stages["parse"]["status"] == "succeeded" and stages["extract"]["status"] == "failed"
    assert stages["extract"]["attempts"] == calls["extract"] == 2  # VERITAS_STAGE_MAX_ATTEMPTS
    job = (await client.get(f"/api/v1/jobs/{body['job_id']}", headers=acct.headers)).json()
    assert job["result"]["failed"] == 1 and job["result"]["failed_ids"] == [doc_id]

    monkeypatch.setattr(document_pipeline, "make_stages", real_make)
    retry = await client.post(f"/api/v1/documents/{doc_id}/retry", headers=acct.headers)
    assert retry.status_code == 202
    assert (
        await client.post(f"/api/v1/documents/{doc_id}/retry", headers=acct.headers)
    ).status_code == 409
    assert await run_job(acct, retry.json()["id"]) is Outcome.SUCCEEDED
    doc = (await client.get(f"/api/v1/documents/{doc_id}", headers=acct.headers)).json()
    stages = {s["stage"]: s for s in doc["stages"]}
    assert doc["status"] == "completed"
    assert stages["parse"]["attempts"] == 1  # resumed from the failed stage, parse not redone
    assert stages["extract"]["attempts"] == 3


async def test_unparseable_input_fails_without_retrying(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    case = await new_case(client, acct)
    broken_pdf = b"%PDF-1.7\nthis is not really a pdf"
    body = await upload(client, acct, case["id"], [("broken.pdf", broken_pdf)])
    await run_job(acct, body["job_id"])
    doc = (
        await client.get(
            f"/api/v1/documents/{body['results'][0]['document_id']}", headers=acct.headers
        )
    ).json()
    parse = next(s for s in doc["stages"] if s["stage"] == "parse")
    assert doc["status"] == "failed" and parse["attempts"] == 1
    assert "unreadable PDF" in doc["error"] or "parse_failed" in doc["error"]
    async with tenant_session(acct.organization_id) as s:
        job = await s.get(Job, uuid.UUID(body["job_id"]))
        assert job is not None and job.status == "succeeded"


async def test_process_case_queues_only_pending_documents(
    client: httpx.AsyncClient,
    shipment_files: list[tuple[str, bytes]],
    no_broker: list[tuple[uuid.UUID, uuid.UUID]],
) -> None:
    acct = await register(client)
    case = await new_case(client, acct)
    body = await upload(client, acct, case["id"], shipment_files[:2])
    await run_job(acct, body["job_id"])
    nothing = (
        await client.post(f"/api/v1/cases/{case['id']}/process", headers=acct.headers)
    ).json()
    assert nothing == {"job_id": None, "document_ids": []}
    await upload(client, acct, case["id"], shipment_files[2:3])
    queued = (await client.post(f"/api/v1/cases/{case['id']}/process", headers=acct.headers)).json()
    assert len(queued["document_ids"]) == 1 and queued["job_id"]


async def _no_sleep(_: float) -> None:
    return None
