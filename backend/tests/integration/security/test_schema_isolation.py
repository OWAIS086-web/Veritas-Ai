# Req: enterprise-security 1.1, 5.2
"""Schema-level isolation: read from the database catalog, so a new table that forgets its
tenant column, RLS, policy or append-only grant fails here without anyone writing a test."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.db import session_scope

pytestmark = pytest.mark.integration

# Tables the application may only insert into and read (decision and event trails).
APPEND_ONLY = [
    "audit_logs",
    "job_events",
    "agent_events",
    "document_versions",
    "finding_decisions",
    "investigator_comments",
    "evidence_requests",
    "comparison_reviews",
]
# Global reference data with no tenant: read-only for the application.
NOT_TENANT_OWNED = {"roles", "alembic_version"}
# Failed logins for an unknown email can't be attributed to an organization; those rows have
# no organization and no tenant can read them (test_rls.py checks that).
NULLABLE_TENANT = {"audit_logs"}


async def _rows(sql: str) -> list[tuple[object, ...]]:
    async with session_scope() as s:
        return [tuple(r) for r in (await s.execute(text(sql))).all()]


async def test_every_tenant_table_has_a_not_null_indexed_tenant_column_rls_and_policy() -> None:
    rows = await _rows(
        """
        SELECT c.relname,
               col.is_nullable,
               c.relrowsecurity,
               (SELECT string_agg(pg_get_expr(p.polqual, p.polrelid), ' ')
                  FROM pg_policy p WHERE p.polrelid = c.oid) AS policy,
               EXISTS (SELECT 1 FROM pg_index i
                        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]
                       WHERE i.indrelid = c.oid AND a.attname = 'organization_id') AS indexed
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
        JOIN information_schema.columns col
          ON col.table_schema = 'public' AND col.table_name = c.relname
         AND col.column_name = 'organization_id'
        WHERE c.relkind = 'r'
        """
    )
    assert len(rows) >= 30, "expected every tenant-owned table to be found"  # 33 at 0009
    problems = []
    for name, nullable, rls, policy, indexed in rows:
        if nullable != "NO" and name not in NULLABLE_TENANT:
            problems.append(f"{name}: organization_id is nullable")
        if not rls:
            problems.append(f"{name}: RLS is disabled")
        if not policy or "app.current_org" not in str(policy):
            problems.append(f"{name}: no tenant policy on app.current_org ({policy})")
        if not indexed:
            problems.append(f"{name}: organization_id has no index")
    assert not problems, "\n".join(problems)


async def test_every_table_is_either_tenant_owned_or_known_global() -> None:
    tables = {
        r[0] for r in await _rows("SELECT tablename FROM pg_tables WHERE schemaname='public'")
    }
    tenant = {
        r[0]
        for r in await _rows(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema='public' AND column_name='organization_id'"
        )
    }
    # Organizations and users are scoped through memberships (their own RLS policies).
    untenanted = tables - tenant - NOT_TENANT_OWNED - {"organizations", "users"}
    assert untenanted == set(), f"tables without organization_id: {sorted(untenanted)}"


async def test_app_role_cannot_bypass_rls_or_own_tables() -> None:
    [(sup, bypass, owned)] = await _rows(
        "SELECT rolsuper, rolbypassrls, "
        "(SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tableowner=current_user) "
        "FROM pg_roles WHERE rolname = current_user"
    )
    assert (sup, bypass, owned) == (False, False, 0)


@pytest.mark.parametrize("table", APPEND_ONLY)
async def test_trails_are_append_only_for_the_app_role(table: str) -> None:
    [(exists, select, insert, update, delete)] = await _rows(
        f"SELECT to_regclass('public.{table}') IS NOT NULL, "
        f"has_table_privilege(current_user, 'public.{table}', 'SELECT'), "
        f"has_table_privilege(current_user, 'public.{table}', 'INSERT'), "
        f"has_table_privilege(current_user, 'public.{table}', 'UPDATE'), "
        f"has_table_privilege(current_user, 'public.{table}', 'DELETE')"
    )
    assert exists, table
    assert (select, insert, update, delete) == (True, True, False, False), table


async def test_cases_are_never_hard_deleted_by_the_app_role_directly() -> None:
    [(delete, purge)] = await _rows(
        "SELECT has_table_privilege(current_user, 'public.cases', 'DELETE'), "
        "has_function_privilege(current_user, 'purge_expired_case(uuid)', 'EXECUTE')"
    )
    # Only through the retention function, which re-checks tenant and expiry.
    assert (delete, purge) == (False, True)
