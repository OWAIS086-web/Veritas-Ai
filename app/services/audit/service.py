"""Append-only audit trail."""

from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import Table, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_scope, set_tenant
from app.models import AuditLog, User
from app.schemas.common import Page
from app.schemas.system import AuditLogOut
from app.services.identity.principal import RequestMeta


async def record(
    session: AsyncSession,
    action: str,
    *,
    organization_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: str | uuid.UUID | None = None,
    meta: RequestMeta | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Insert an audit row in the current transaction. Metadata must never hold secrets.

    Uses a Core INSERT without RETURNING. Postgres applies the SELECT policy to RETURNING
    rows, and unattributed rows (organization_id NULL) are deliberately unreadable by tenants.
    """
    await session.execute(
        insert(cast(Table, AuditLog.__table__)).values(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            ip=meta.ip if meta else None,
            user_agent=(meta.user_agent or "")[:300] if meta and meta.user_agent else None,
            metadata=metadata or {},
        )
    )


async def record_independent(
    action: str,
    *,
    organization_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None = None,
    meta: RequestMeta | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Audit in its own transaction, so it survives a rollback of the caller's transaction
    (used for failed logins and token-reuse detection, where the request then fails)."""
    async with session_scope() as session:
        if organization_id is not None:
            await set_tenant(session, organization_id)
        await record(
            session,
            action,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            meta=meta,
            metadata=metadata,
        )


async def list_for_org(
    session: AsyncSession, organization_id: uuid.UUID, limit: int, cursor: str | None
) -> Page[AuditLogOut]:
    stmt = (
        select(AuditLog, User.email)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .where(AuditLog.organization_id == organization_id)
        .order_by(AuditLog.id.desc())
        .limit(limit + 1)
    )
    if cursor:
        try:
            before = int(cursor)
        except ValueError:
            before = 0
        stmt = stmt.where(AuditLog.id < before)
    rows = (await session.execute(stmt)).all()
    items = [
        AuditLogOut(
            id=log.id,
            action=log.action,
            resource_type=log.resource_type,
            resource_id=log.resource_id,
            actor_user_id=log.actor_user_id,
            actor_email=email,
            ip=log.ip,
            created_at=log.created_at,
            metadata=log.metadata_,
        )
        for log, email in rows[:limit]
    ]
    next_cursor = str(items[-1].id) if len(rows) > limit and items else None
    return Page[AuditLogOut](items=items, next_cursor=next_cursor)
