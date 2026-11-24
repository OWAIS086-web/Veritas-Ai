"""Helpers for row-level security and grants, shared by every migration.

Identifiers can't be bound parameters, so the table and role names are checked against a
strict pattern before being placed into DDL. The `nosemgrep` annotations below mark exactly
those statements for `scripts/security-scan` (rule veritas-sql-string-formatting).
"""

from __future__ import annotations

import re

from alembic import op

from migrations.settings import get_migration_settings

_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
CURRENT_ORG = "NULLIF(current_setting('app.current_org', true), '')::uuid"


def _ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"unsafe identifier: {name!r}")
    return name


def app_role() -> str:
    return _ident(get_migration_settings().app_db_user)


def readonly_role() -> str:
    return _ident(get_migration_settings().ro_db_user)


def enable_tenant_rls(table: str, column: str = "organization_id") -> None:
    t, c = _ident(table), _ident(column)
    # nosemgrep: veritas-sql-string-formatting
    op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
    # nosemgrep: veritas-sql-string-formatting
    op.execute(
        f"CREATE POLICY {t}_tenant ON {t} USING ({c} = {CURRENT_ORG}) "
        f"WITH CHECK ({c} = {CURRENT_ORG})"
    )


def grant(table: str, privileges: str, sequence: str | None = None) -> None:
    allowed = {"SELECT", "INSERT", "UPDATE", "DELETE"}
    privs = [p.strip().upper() for p in privileges.split(",")]
    if not privs or any(p not in allowed for p in privs):
        raise ValueError(f"unsupported privileges: {privileges!r}")
    t = _ident(table)
    # nosemgrep: veritas-sql-string-formatting
    op.execute(f"GRANT {', '.join(privs)} ON {t} TO {app_role()}")
    # nosemgrep: veritas-sql-string-formatting
    op.execute(f"GRANT SELECT ON {t} TO {readonly_role()}")
    if sequence:
        # nosemgrep: veritas-sql-string-formatting
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {_ident(sequence)} TO {app_role()}")


def grant_execute(function_signature: str) -> None:
    # Signature like "auth_memberships(uuid)"; validated as name + simple arg list.
    if not re.match(r"^[a-z_][a-z0-9_]*\([a-z0-9_, ]*\)$", function_signature):
        raise ValueError(f"unsafe function signature: {function_signature!r}")
    # nosemgrep: veritas-sql-string-formatting
    op.execute(f"REVOKE ALL ON FUNCTION {function_signature} FROM PUBLIC")
    # nosemgrep: veritas-sql-string-formatting
    op.execute(f"GRANT EXECUTE ON FUNCTION {function_signature} TO {app_role()}")
