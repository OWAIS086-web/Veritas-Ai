"""retention purge: list organizations with a retention period, delete one expired case

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-24 18:30:00

The application role keeps no DELETE grant on `cases`. It can remove a case only through
`purge_expired_case`, which deletes the case of the caller's tenant (`app.current_org`) only
when that organization's retention period has passed for it. Everything under the case is
removed by the existing ON DELETE CASCADE foreign keys. `audit_logs` has no foreign key to
cases, so the audit trail stays.
"""

from collections.abc import Sequence

from alembic import op

from migrations.rls import grant_execute

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS = [
    # The worker lists the organizations that set a retention period (ids and days only),
    # then purges each one inside its own tenant session.
    """
    CREATE FUNCTION retention_organizations()
    RETURNS TABLE (organization_id uuid, retention_days integer)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
        SELECT o.id, o.retention_days FROM organizations o WHERE o.retention_days IS NOT NULL
    $$
    """,
    # A case expires when its last change (its deletion, if it was soft-deleted) is older
    # than the organization's retention period.
    """
    CREATE FUNCTION purge_expired_case(p_case uuid)
    RETURNS boolean
    LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
        WITH gone AS (
            DELETE FROM cases c
            USING organizations o
            WHERE c.id = p_case
              AND c.organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
              AND o.id = c.organization_id
              AND o.retention_days IS NOT NULL
              AND COALESCE(c.deleted_at, c.updated_at)
                  < now() - make_interval(days => o.retention_days)
            RETURNING c.id
        )
        SELECT EXISTS (SELECT 1 FROM gone)
    $$
    """,
]
FUNCTIONS = ["retention_organizations()", "purge_expired_case(uuid)"]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)
    for signature in FUNCTIONS:
        grant_execute(signature)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS purge_expired_case(uuid)")
    op.execute("DROP FUNCTION IF EXISTS retention_organizations()")
