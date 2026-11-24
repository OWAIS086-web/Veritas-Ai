# Req: enterprise-security 5.1
"""Retention purge against real Postgres and object storage."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select, text, update

from app.core.db import session_scope, set_tenant, tenant_session
from app.integrations.storage.base import resource_prefix
from app.integrations.storage.s3_store import get_store
from app.models import AuditLog, Case, Document, DocumentPage, Organization
from app.services.system.retention import purge_expired
from tests.integration.conftest import Account, register
from tests.integration.test_cases_and_upload import new_case, upload
from tests.integration.test_pipeline import SAMPLES, run_job

pytestmark = pytest.mark.integration


async def _case_with_document(
    client: httpx.AsyncClient, acct: Account, title: str
) -> tuple[str, str]:
    case = await new_case(client, acct, title=title)
    data = (SAMPLES / "shipment-case" / "02_commercial_invoice.pdf").read_bytes()
    body = await upload(client, acct, case["id"], [(f"{title}.pdf", data)])
    assert (await run_job(acct, body["job_id"])).value == "succeeded"
    return case["id"], body["results"][0]["document_id"]


async def _set(
    org: uuid.UUID,
    case_id: str | None = None,
    *,
    days: int | None = None,
    age_days: int | None = None,
    deleted: bool = False,
) -> None:
    async with tenant_session(org) as s:
        if days is not None:
            await s.execute(
                update(Organization).where(Organization.id == org).values(retention_days=days)
            )
        if case_id is not None and age_days is not None:
            when = datetime.now(UTC) - timedelta(days=age_days)
            values = {"updated_at": when, **({"deleted_at": when} if deleted else {})}
            await s.execute(update(Case).where(Case.id == uuid.UUID(case_id)).values(**values))


async def _exists(org: uuid.UUID, case_id: str) -> bool:
    async with tenant_session(org) as s:
        return (
            await s.scalar(
                select(func.count()).select_from(Case).where(Case.id == uuid.UUID(case_id))
            )
            == 1
        )


async def test_expired_cases_lose_rows_and_files_and_the_rest_stays(
    client: httpx.AsyncClient,
) -> None:
    acct = await register(client, org_name="Retention Org")
    keep_forever = await register(client, org_name="No Retention Org")
    org = acct.organization_id
    old, old_doc = await _case_with_document(client, acct, "old")
    deleted, _ = await _case_with_document(client, acct, "deleted")
    recent, recent_doc = await _case_with_document(client, acct, "recent")
    untouched, _ = await _case_with_document(client, keep_forever, "ancient")
    await _set(org, days=30)
    await _set(org, old, age_days=31)
    await _set(org, deleted, age_days=31, deleted=True)
    await _set(org, recent, age_days=5)
    await _set(keep_forever.organization_id, untouched, age_days=4000)
    async with tenant_session(org) as s:
        old_key = (await s.get(Document, uuid.UUID(old_doc))).storage_key  # type: ignore[union-attr]
    store = get_store()
    assert await store.exists(old_key)

    result = await purge_expired(store)

    assert result["cases"] >= 2 and result["failed"] == 0
    assert not await _exists(org, old) and not await _exists(org, deleted)
    assert await _exists(org, recent)
    assert await _exists(keep_forever.organization_id, untouched)
    assert not await store.exists(old_key)
    async with tenant_session(org) as s:
        recent_key = (await s.get(Document, uuid.UUID(recent_doc))).storage_key  # type: ignore[union-attr]
        orphans = await s.scalar(
            select(func.count())
            .select_from(DocumentPage)
            .where(DocumentPage.document_id == uuid.UUID(old_doc))
        )
        entry = await s.scalar(
            select(AuditLog).where(
                AuditLog.organization_id == org, AuditLog.action == "retention.purge"
            )
        )
    assert await store.exists(recent_key)
    assert orphans == 0  # cascaded
    assert entry is not None
    # Counts only: no titles, filenames or text.
    assert set(entry.metadata_) <= {"cases", "documents", "objects", "failed", "retention_days"}
    assert entry.metadata_["cases"] == 2 and entry.metadata_["objects"] >= 2
    # A second run finds nothing more to do.
    again = await purge_expired(store)
    assert again["cases"] == 0


async def test_the_purge_function_refuses_another_tenant_and_unexpired_cases(
    client: httpx.AsyncClient,
) -> None:
    a = await register(client, org_name="Purge A")
    b = await register(client, org_name="Purge B")
    case = await new_case(client, a, title="Victim")
    await _set(a.organization_id, days=1)
    await _set(a.organization_id, case["id"], age_days=0)
    async with session_scope() as s:
        await set_tenant(s, a.organization_id)
        assert await s.scalar(text("SELECT purge_expired_case(:c)"), {"c": case["id"]}) is False
    await _set(a.organization_id, case["id"], age_days=10)
    for org in (b.organization_id, None):
        async with session_scope() as s:
            if org:
                await set_tenant(s, org)
            assert await s.scalar(text("SELECT purge_expired_case(:c)"), {"c": case["id"]}) is False
    assert await _exists(a.organization_id, case["id"])
    # Direct deletion is not granted at all.
    with pytest.raises(Exception, match="permission denied"):
        async with session_scope() as s:
            await set_tenant(s, a.organization_id)
            await s.execute(text("DELETE FROM cases WHERE id = :c"), {"c": case["id"]})


async def test_storage_deletion_only_accepts_a_full_resource_prefix() -> None:
    store = get_store()
    org, rid = uuid.uuid4(), uuid.uuid4()
    for prefix in ("", f"{org}/", f"{org}", f"{org}/{rid}", "../", f"{org}/{rid}/original"):
        with pytest.raises(ValueError):
            await store.delete_prefix(prefix)
    assert await store.delete_prefix(resource_prefix(org, rid)) == 0
