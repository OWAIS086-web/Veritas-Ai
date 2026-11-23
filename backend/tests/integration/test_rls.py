# Req: platform-foundation 4.3; enterprise-security 1.1; authentication-rbac 8.1
"""Direct-SQL tests of row-level security, as the real non-owner application role."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import session_scope, set_tenant
from tests.integration.conftest import register

pytestmark = pytest.mark.integration

TENANT_TABLES = ["organization_members", "refresh_tokens", "jobs", "job_events"]


async def test_app_role_is_not_owner_superuser_or_bypassrls() -> None:
    async with session_scope() as s:
        row = (
            await s.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()
        owned = await s.scalar(
            text(
                "SELECT count(*) FROM pg_tables WHERE schemaname='public' "
                "AND tableowner = current_user"
            )
        )
    assert row.rolsuper is False and row.rolbypassrls is False
    assert owned == 0


async def test_every_table_with_organization_id_has_rls_and_a_policy() -> None:
    async with session_scope() as s:
        rows = (
            await s.execute(
                text(
                    """
                    SELECT c.relname, c.relrowsecurity,
                           (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policies
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
                    WHERE c.relkind = 'r' AND EXISTS (
                        SELECT 1 FROM information_schema.columns col
                        WHERE col.table_schema = 'public' AND col.table_name = c.relname
                          AND col.column_name = 'organization_id')
                    """
                )
            )
        ).all()
    tables = {r.relname: r for r in rows}
    assert set(TENANT_TABLES) | {"audit_logs"} <= set(tables)
    for name, r in tables.items():
        assert r.relrowsecurity, f"{name} has RLS disabled"
        assert r.policies >= 1, f"{name} has no policy"


async def test_rows_invisible_across_tenants_and_without_context(
    client: httpx.AsyncClient,
) -> None:
    a = await register(client, org_name="RLS A")
    b = await register(client, org_name="RLS B")
    for table in [*TENANT_TABLES[:2], "organizations"]:
        column = "id" if table == "organizations" else "organization_id"
        async with session_scope() as s:
            await set_tenant(s, a.organization_id)
            # Table and column names come from the fixed list above, not from input.
            orgs_seen = set(
                (await s.scalars(text(f"SELECT {column} FROM {table}"))).all()  # noqa: S608
            )
        assert orgs_seen == {a.organization_id}, table
        assert b.organization_id not in orgs_seen
        async with session_scope() as s:
            none_seen = (await s.scalars(text(f"SELECT {column} FROM {table}"))).all()  # noqa: S608
        assert none_seen == [], f"{table} visible without tenant context"


RECEIPT_PDF = (
    Path(__file__).resolve().parents[3] / "sample-data" / "shipment-case" / "05_payment_receipt.pdf"
).read_bytes()
PHASE2_TABLES = [
    "cases",
    "documents",
    "document_stages",
    "document_pages",
    "extraction_runs",
    "extracted_fields",
]


async def test_document_tables_are_invisible_across_tenants(client: httpx.AsyncClient) -> None:
    """Direct SQL as veritas_app: each organization sees only its own document rows."""
    from app.integrations.storage.s3_store import get_store
    from app.workflows.document_pipeline import process_document

    orgs = []
    for name in ("Docs A", "Docs B"):
        acct = await register(client, org_name=name)
        case = (
            await client.post("/api/v1/cases", headers=acct.headers, json={"title": f"{name} case"})
        ).json()
        up = (
            await client.post(
                f"/api/v1/cases/{case['id']}/documents",
                headers=acct.headers,
                files=[("files", ("r.pdf", RECEIPT_PDF, "application/pdf"))],
            )
        ).json()
        await process_document(
            acct.organization_id, uuid.UUID(up["results"][0]["document_id"]), get_store()
        )
        orgs.append(acct)
    a, b = orgs
    for table in PHASE2_TABLES:
        async with session_scope() as s:
            await set_tenant(s, a.organization_id)
            seen = set((await s.scalars(text(f"SELECT organization_id FROM {table}"))).all())  # noqa: S608
        assert seen == {a.organization_id}, table
        async with session_scope() as s:
            empty = (await s.scalars(text(f"SELECT organization_id FROM {table}"))).all()  # noqa: S608
        assert empty == [], f"{table} visible without tenant context"
    assert b.organization_id not in seen


async def test_cannot_write_rows_for_another_tenant(client: httpx.AsyncClient) -> None:
    a = await register(client, org_name="Writer A")
    b = await register(client, org_name="Victim B")
    with pytest.raises(DBAPIError, match="row-level security"):
        async with session_scope() as s:
            await set_tenant(s, a.organization_id)
            await s.execute(
                text(
                    "INSERT INTO jobs (id, organization_id, kind, status, progress, attempts, "
                    "max_attempts, payload, updated_at) VALUES (:id, :org, 'x', 'queued', 0, 0, "
                    "1, '{}', now())"
                ),
                {"id": uuid.uuid4(), "org": b.organization_id},
            )


async def test_cannot_move_a_row_to_another_tenant(client: httpx.AsyncClient) -> None:
    a = await register(client, org_name="Mover A")
    b = await register(client, org_name="Target B")
    with pytest.raises(DBAPIError, match="row-level security"):
        async with session_scope() as s:
            await set_tenant(s, a.organization_id)
            await s.execute(
                text(
                    "UPDATE organization_members SET organization_id = :b "
                    "WHERE organization_id = :a"
                ),
                {"a": a.organization_id, "b": b.organization_id},
            )


async def test_audit_log_is_append_only_for_app_role(client: httpx.AsyncClient) -> None:
    a = await register(client)
    for stmt in ("UPDATE audit_logs SET action = 'tampered'", "DELETE FROM audit_logs"):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with session_scope() as s:
                await set_tenant(s, a.organization_id)
                await s.execute(text(stmt))


async def test_unattributed_audit_rows_are_not_readable_by_tenants(
    client: httpx.AsyncClient,
) -> None:
    a = await register(client)
    await client.post(
        "/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-123"}
    )
    async with session_scope() as s:
        await set_tenant(s, a.organization_id)
        nulls = await s.scalar(
            text("SELECT count(*) FROM audit_logs WHERE organization_id IS NULL")
        )
    assert nulls == 0
