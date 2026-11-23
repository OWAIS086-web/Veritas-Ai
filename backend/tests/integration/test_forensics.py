"""Document forensics end to end: the synthetic forensic fixtures go through the real pipeline
(parse → classify → extract → validate → forensics) against Postgres and object storage, and
the persisted anomalies must match the fixture manifest. Also covers the API, the severity cap
enforced by the database, rerun idempotency and tenant isolation."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.db import session_scope, set_tenant, tenant_session
from app.integrations.storage.s3_store import get_store
from app.models import Document, ExtractedField, Finding, ForensicAnomaly, ForensicRun
from app.models.forensics import MANDATORY_LIMITATION
from app.services.forensics.model import overlaps
from app.services.forensics.runner import run_document_forensics
from tests.integration.conftest import Account, register
from tests.integration.test_cases_and_upload import new_case, upload
from tests.integration.test_pipeline import run_job

pytestmark = pytest.mark.integration
FORENSICS = Path(__file__).resolve().parents[3] / "sample-data" / "forensics"
MANIFEST = json.loads((FORENSICS / "manifest.json").read_text(encoding="utf-8"))

# Upload order matters. Stamps are compared with the stamps of documents processed earlier
# in the case, so the altered receipt comes last; the second version follows the first.
BATCHES = [
    [
        "clean_invoice.pdf",
        "edited_invoice.pdf",
        "backdated_invoice.pdf",
        "receipt_same_stamp.pdf",
        "versions/v1/forensic_invoice.pdf",
        "clean_scan.pdf",
        "recompressed_scan.pdf",
    ],
    ["versions/v2/forensic_invoice.pdf"],
    ["receipt_altered_stamp.pdf"],
]


@dataclass
class ForensicCase:
    acct: Account
    case_id: str
    ids: dict[str, str]  # fixture path → document id


@pytest.fixture(scope="module")
async def forensic_case(app: Any) -> AsyncIterator[ForensicCase]:
    transport = httpx.ASGITransport(app=app, client=("10.9.9.7", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        acct = await register(c, org_name="Forensics Lab Org")
        case = await new_case(c, acct, title="Forensic fixtures")
        ids: dict[str, str] = {}
        for batch in BATCHES:
            files = [(Path(p).name, (FORENSICS / p).read_bytes()) for p in batch]
            body = await upload(c, acct, case["id"], files)
            for path, result in zip(batch, body["results"], strict=True):
                assert result["status"] == "accepted", result
                ids[path] = result["document_id"]
            assert (await run_job(acct, body["job_id"])).value == "succeeded"
        yield ForensicCase(acct, case["id"], ids)


async def _run(client: httpx.AsyncClient, fc: ForensicCase, path: str) -> dict[str, Any]:
    resp = await client.get(f"/api/v1/documents/{fc.ids[path]}/forensics", headers=fc.acct.headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body is not None, path
    return dict(body)


@pytest.mark.slow
async def test_every_fixture_yields_exactly_its_expected_anomaly_types(
    client: httpx.AsyncClient, forensic_case: ForensicCase
) -> None:
    for path, expected in MANIFEST["expected"].items():
        run = await _run(client, forensic_case, path)
        assert run["status"] == "succeeded", (path, run["structure"].get("errors"))
        assert {a["type"] for a in run["anomalies"]} == set(expected), path
        assert MANDATORY_LIMITATION in run["limitations"], path
        for a in run["anomalies"]:
            assert a["severity"] in {"info", "low", "medium"}
            assert a["requires_review"] is (a["severity"] == "medium")
            assert a["explanation"].strip()
            text_ = a["explanation"].lower()
            assert "forged" not in text_ and "authentic" not in text_, a["explanation"]


@pytest.mark.slow
async def test_regions_point_at_the_planted_changes(
    client: httpx.AsyncClient, forensic_case: ForensicCase
) -> None:
    regions = MANIFEST["regions"]
    planted = {
        "versions/v2/forensic_invoice.pdf": ("version_difference", regions["total"]),
        "receipt_altered_stamp.pdf": ("stamp_appearance_variation", regions["stamp"]),
        "recompressed_scan.pdf": ("localized_compression_anomaly", regions["jpeg_region"]),
    }
    for path, (kind, region) in planted.items():
        run = await _run(client, forensic_case, path)
        hits = [a for a in run["anomalies"] if a["type"] == kind]
        assert hits, path
        assert all(a["page_number"] == 1 and a["region"] for a in hits), path
        assert any(overlaps(a["region"], region) for a in hits), (path, hits)


@pytest.mark.slow
async def test_field_references_in_metrics_resolve_to_real_extracted_fields(
    client: httpx.AsyncClient, forensic_case: ForensicCase
) -> None:
    org = forensic_case.acct.organization_id
    referenced: list[tuple[str, str]] = []
    for path in MANIFEST["expected"]:
        run = await _run(client, forensic_case, path)
        for a in run["anomalies"]:
            ids = list(a["metrics"].get("fields", []))
            if a["metrics"].get("field_id"):
                ids.append(a["metrics"]["field_id"])
            referenced += [(run["document_id"], i) for i in ids]
    # The font anomaly and the version change both sit on the extracted total.
    assert referenced
    async with tenant_session(org) as s:
        for document_id, field_id in referenced:
            field = await s.get(ExtractedField, uuid.UUID(field_id))
            assert field is not None and str(field.document_id) == document_id


@pytest.mark.slow
async def test_case_summary_lists_documents_to_review_first(
    client: httpx.AsyncClient, forensic_case: ForensicCase
) -> None:
    fc = forensic_case
    resp = await client.get(f"/api/v1/cases/{fc.case_id}/forensics", headers=fc.acct.headers)
    assert resp.status_code == 200, resp.text
    summary = resp.json()
    assert {row["document_id"] for row in summary} == set(fc.ids.values())
    mediums = [row["medium"] for row in summary]
    assert mediums == sorted(mediums, reverse=True)
    by_id = {row["document_id"]: row for row in summary}
    for path, expected in MANIFEST["expected"].items():
        row = by_id[fc.ids[path]]
        assert row["status"] == "succeeded"
        assert set(row["types"]) == set(expected), path
        assert row["anomalies"] >= row["medium"] + row["low"]
        assert (row["anomalies"] > 0) == bool(expected), path


@pytest.mark.slow
async def test_pipeline_records_the_forensics_stage_and_creates_no_findings(
    client: httpx.AsyncClient, forensic_case: ForensicCase
) -> None:
    fc = forensic_case
    doc = (
        await client.get(
            f"/api/v1/documents/{fc.ids['edited_invoice.pdf']}", headers=fc.acct.headers
        )
    ).json()
    assert [s["stage"] for s in doc["stages"]][-1] == "forensics"
    assert all(s["status"] == "succeeded" for s in doc["stages"])
    # Forensic anomalies are observations for review; the comparison module never sees them.
    async with tenant_session(fc.acct.organization_id) as s:
        types = set(
            await s.scalars(select(Finding.type).where(Finding.case_id == uuid.UUID(fc.case_id)))
        )
    assert not any("forensic" in t or "stamp" in t or "compression" in t for t in types)


@pytest.mark.slow
async def test_rerun_replaces_the_run_without_duplicates(
    forensic_case: ForensicCase,
) -> None:
    org = forensic_case.acct.organization_id
    doc_id = uuid.UUID(forensic_case.ids["edited_invoice.pdf"])

    async def counts() -> tuple[int, int]:
        async with tenant_session(org) as s:
            runs = await s.scalar(
                select(func.count())
                .select_from(ForensicRun)
                .where(ForensicRun.document_id == doc_id)
            )
            anomalies = await s.scalar(
                select(func.count())
                .select_from(ForensicAnomaly)
                .where(ForensicAnomaly.document_id == doc_id)
            )
        return int(runs or 0), int(anomalies or 0)

    async with tenant_session(org) as s:
        doc = await s.get(Document, doc_id)
        assert doc is not None
    # The first rerun may add a stamp anomaly: the altered receipt was processed after this
    # document, so its stamp is now part of the case. A second rerun sees the same inputs.
    await run_document_forensics(org, doc, get_store())
    once = await counts()
    await run_document_forensics(org, doc, get_store())
    assert once[0] == 1 and once[1] >= 3
    assert await counts() == once


@pytest.mark.slow
async def test_database_refuses_a_severity_above_medium(forensic_case: ForensicCase) -> None:
    org = forensic_case.acct.organization_id
    async with tenant_session(org) as s:
        run = await s.scalar(
            select(ForensicRun).where(
                ForensicRun.document_id == uuid.UUID(forensic_case.ids["clean_invoice.pdf"])
            )
        )
        assert run is not None
        run_id, doc_id = run.id, run.document_id
    with pytest.raises(DBAPIError, match=r"severity|check constraint"):
        async with session_scope() as s:
            await set_tenant(s, org)
            await s.execute(
                text(
                    "INSERT INTO forensic_anomalies (id, organization_id, forensic_run_id,"
                    " document_id, type, severity, explanation, metrics, requires_review,"
                    " created_at) VALUES (gen_random_uuid(), :org, :run, :doc, 'probe', 'high',"
                    " 'probe', '{}'::jsonb, true, now())"
                ),
                {"org": org, "run": run_id, "doc": doc_id},
            )


@pytest.mark.slow
async def test_forensics_are_isolated_between_organizations(
    client: httpx.AsyncClient, forensic_case: ForensicCase
) -> None:
    outsider = await register(client, org_name="Forensics Outsider")
    doc_id = forensic_case.ids["edited_invoice.pdf"]
    for path in (
        f"/api/v1/documents/{doc_id}/forensics",
        f"/api/v1/cases/{forensic_case.case_id}/forensics",
        f"/api/v1/documents/{uuid.uuid4()}/forensics",
        f"/api/v1/cases/{uuid.uuid4()}/forensics",
    ):
        resp = await client.get(path, headers=outsider.headers)
        assert resp.status_code == 404, f"{path}: {resp.status_code}"
    for table in ("forensic_runs", "forensic_anomalies"):
        async with session_scope() as s:
            await set_tenant(s, outsider.organization_id)
            seen = (await s.scalars(text(f"SELECT organization_id FROM {table}"))).all()  # noqa: S608
        assert seen == [], table
        async with session_scope() as s:
            unscoped = (await s.scalars(text(f"SELECT organization_id FROM {table}"))).all()  # noqa: S608
        assert unscoped == [], f"{table} visible without tenant context"
        async with session_scope() as s:
            await set_tenant(s, forensic_case.acct.organization_id)
            own = set((await s.scalars(text(f"SELECT organization_id FROM {table}"))).all())  # noqa: S608
        assert own == {forensic_case.acct.organization_id}, table
