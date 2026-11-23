"""Organizations: creation, listing for the caller, and updates."""

from __future__ import annotations

import re
import secrets
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_tenant
from app.core.errors import NotFoundError
from app.core.permissions import Role
from app.models import Organization, OrganizationMember
from app.models import Role as RoleModel
from app.schemas.auth import OrganizationOut
from app.schemas.organizations import MyOrganizationOut, OrganizationUpdate
from app.services.audit import service as audit
from app.services.identity.principal import Principal, RequestMeta


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "org"
    return f"{base}-{secrets.token_hex(3)}"


async def role_id(session: AsyncSession, role: Role) -> int:
    value = await session.scalar(select(RoleModel.id).where(RoleModel.key == role.value))
    if value is None:
        raise RuntimeError(f"role {role} is not seeded")
    return value


async def create_with_admin(session: AsyncSession, name: str, user_id: uuid.UUID) -> Organization:
    """Create an organization with `user_id` as its admin. Leaves the transaction's tenant
    context set to the new organization."""
    org = Organization(id=uuid.uuid4(), name=name.strip(), slug=slugify(name))
    await set_tenant(session, org.id)
    session.add(org)
    await session.flush()
    session.add(
        OrganizationMember(
            organization_id=org.id, user_id=user_id, role_id=await role_id(session, Role.ORG_ADMIN)
        )
    )
    await session.flush()
    return org


async def list_mine(session: AsyncSession, user_id: uuid.UUID) -> list[MyOrganizationOut]:
    rows = await session.execute(
        text(
            "SELECT organization_id, organization_name, organization_slug, role_key, joined_at "
            "FROM auth_memberships(:uid)"
        ),
        {"uid": user_id},
    )
    return [
        MyOrganizationOut(
            id=r.organization_id,
            name=r.organization_name,
            slug=r.organization_slug,
            role=Role(r.role_key),
            joined_at=r.joined_at,
        )
        for r in rows
    ]


async def create(
    session: AsyncSession, principal: Principal, name: str, meta: RequestMeta
) -> OrganizationOut:
    org = await create_with_admin(session, name, principal.user_id)
    await audit.record(
        session,
        "organization.create",
        organization_id=org.id,
        actor_user_id=principal.user_id,
        resource_type="organization",
        resource_id=org.id,
        meta=meta,
    )
    return OrganizationOut.model_validate(org)


async def _get_active(
    session: AsyncSession, principal: Principal, organization_id: uuid.UUID
) -> Organization:
    # Tokens are scoped to one organization. Any other id, including another
    # organization the user belongs to, is "not found" from this token's point of view.
    if organization_id != principal.organization_id:
        raise NotFoundError("Organization not found.")
    org = await session.scalar(
        select(Organization).where(Organization.id == principal.organization_id)
    )
    if org is None:
        raise NotFoundError("Organization not found.")
    return org


async def get(
    session: AsyncSession, principal: Principal, organization_id: uuid.UUID
) -> OrganizationOut:
    return OrganizationOut.model_validate(await _get_active(session, principal, organization_id))


async def update(
    session: AsyncSession,
    principal: Principal,
    organization_id: uuid.UUID,
    changes: OrganizationUpdate,
    meta: RequestMeta,
) -> OrganizationOut:
    org = await _get_active(session, principal, organization_id)
    changed = changes.model_dump(exclude_unset=True)
    if "name" in changed and changed["name"] is not None:
        org.name = changed["name"].strip()
    if "retention_days" in changed:
        org.retention_days = changed["retention_days"]
    await session.flush()
    await audit.record(
        session,
        "organization.update",
        organization_id=org.id,
        actor_user_id=principal.user_id,
        resource_type="organization",
        resource_id=org.id,
        meta=meta,
        metadata={"fields": sorted(changed)},
    )
    return OrganizationOut.model_validate(org)
