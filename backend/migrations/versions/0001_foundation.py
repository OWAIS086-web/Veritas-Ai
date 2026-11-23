"""foundation: identity, audit, jobs, with row-level security

Revision ID: 0001
Revises:
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.rls import CURRENT_ORG, enable_tenant_rls, grant, grant_execute

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = [
    (1, "org_admin", "Organization Admin"),
    (2, "investigation_manager", "Investigation Manager"),
    (3, "investigator", "Investigator"),
    (4, "reviewer", "Reviewer"),
    (5, "read_only_analyst", "Read-only Analyst"),
]


def _tables() -> None:
    op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("slug", name=op.f("uq_organizations_slug")),
    )
    op.create_table(
        "roles",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("key", name=op.f("uq_roles_key")),
    )
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=True),
        sa.Column("resource_id", sa.String(length=80), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_logs_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_audit_logs_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(
        "ix_audit_logs_org_created", "audit_logs", ["organization_id", "created_at"], unique=False
    )
    op.create_table(
        "jobs",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_jobs_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_jobs_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index(op.f("ix_jobs_organization_id"), "jobs", ["organization_id"], unique=False)
    op.create_table(
        "organization_members",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.SmallInteger(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_members_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name=op.f("fk_organization_members_role_id_roles")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_organization_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_members")),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            name=op.f("uq_organization_members_organization_id_user_id"),
        ),
    )
    op.create_index(
        op.f("ix_organization_members_organization_id"),
        "organization_members",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_organization_members_user_id"),
        "organization_members",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_refresh_tokens_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"], unique=False)
    op.create_index(
        op.f("ix_refresh_tokens_organization_id"),
        "refresh_tokens",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "job_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=80), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_job_events_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_job_events_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_events")),
        sa.UniqueConstraint("job_id", "seq", name=op.f("uq_job_events_job_id_seq")),
    )
    op.create_index(
        op.f("ix_job_events_organization_id"), "job_events", ["organization_id"], unique=False
    )


def _security() -> None:
    # Seed the five roles.
    roles = sa.table(
        "roles",
        sa.column("id", sa.SmallInteger),
        sa.column("key", sa.String),
        sa.column("name", sa.String),
    )
    op.bulk_insert(roles, [{"id": i, "key": k, "name": n} for i, k, n in ROLES])

    # Tenant-owned tables: RLS keyed on app.current_org.
    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY organizations_tenant ON organizations USING (id = {CURRENT_ORG}) "
        f"WITH CHECK (id = {CURRENT_ORG})"
    )
    for table in ("organization_members", "refresh_tokens", "jobs", "job_events"):
        enable_tenant_rls(table)

    # audit_logs: read own org only; insert own org or unattributed (null) rows.
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY audit_logs_read ON audit_logs FOR SELECT "
        f"USING (organization_id = {CURRENT_ORG})"
    )
    op.execute(
        f"CREATE POLICY audit_logs_insert ON audit_logs FOR INSERT "
        f"WITH CHECK (organization_id IS NULL OR organization_id = {CURRENT_ORG})"
    )

    # Least-privilege grants for the application role (read-only role gets SELECT).
    grant("organizations", "SELECT, INSERT, UPDATE")
    grant("users", "SELECT, INSERT, UPDATE")
    grant("roles", "SELECT")
    grant("organization_members", "SELECT, INSERT, UPDATE, DELETE")
    grant("refresh_tokens", "SELECT, INSERT, UPDATE")
    grant("audit_logs", "SELECT, INSERT", sequence="audit_logs_id_seq")  # append-only
    grant("jobs", "SELECT, INSERT, UPDATE")
    grant("job_events", "SELECT, INSERT", sequence="job_events_id_seq")

    # Pre-authentication lookups that must cross tenants. Owner-owned SECURITY DEFINER
    # functions return only the minimal columns, and only the app role may call them.
    op.execute(
        """
        CREATE FUNCTION auth_memberships(p_user_id uuid)
        RETURNS TABLE (organization_id uuid, organization_name varchar, organization_slug varchar,
                       role_key varchar, joined_at timestamptz)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
            SELECT m.organization_id, o.name, o.slug, r.key, m.created_at
            FROM organization_members m
            JOIN organizations o ON o.id = m.organization_id
            JOIN roles r ON r.id = m.role_id
            WHERE m.user_id = p_user_id
            ORDER BY m.created_at, m.organization_id
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION auth_find_refresh(p_token_hash varchar)
        RETURNS TABLE (id uuid, organization_id uuid, user_id uuid, family_id uuid,
                       expires_at timestamptz, revoked_at timestamptz)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
            SELECT t.id, t.organization_id, t.user_id, t.family_id, t.expires_at, t.revoked_at
            FROM refresh_tokens t WHERE t.token_hash = p_token_hash
        $$
        """
    )
    grant_execute("auth_memberships(uuid)")
    grant_execute("auth_find_refresh(varchar)")


def upgrade() -> None:
    _tables()
    _security()


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth_find_refresh(varchar)")
    op.execute("DROP FUNCTION IF EXISTS auth_memberships(uuid)")
    op.drop_index(op.f("ix_job_events_organization_id"), table_name="job_events")
    op.drop_table("job_events")
    op.drop_index(op.f("ix_refresh_tokens_organization_id"), table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index(op.f("ix_organization_members_user_id"), table_name="organization_members")
    op.drop_index(
        op.f("ix_organization_members_organization_id"), table_name="organization_members"
    )
    op.drop_table("organization_members")
    op.drop_index(op.f("ix_jobs_organization_id"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_audit_logs_org_created", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("users")
    op.drop_table("roles")
    op.drop_table("organizations")
