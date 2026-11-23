"""Organization membership and role management."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.core.permissions import Role
from app.models import OrganizationMember, RefreshToken, User
from app.models import Role as RoleModel
from app.schemas.organizations import MemberOut
from app.services.audit import service as audit
from app.services.identity.organizations import role_id
from app.services.identity.principal import Principal, RequestMeta


def _check_org(principal: Principal, organization_id: uuid.UUID) -> None:
    if organization_id != principal.organization_id:
        raise NotFoundError("Organization not found.")


def _out(member: OrganizationMember) -> MemberOut:
    return MemberOut(
        user_id=member.user_id,
        email=member.user.email,
        full_name=member.user.full_name,
        role=Role(member.role.key),
        created_at=member.created_at,
    )


async def list_members(
    session: AsyncSession, principal: Principal, organization_id: uuid.UUID
) -> list[MemberOut]:
    _check_org(principal, organization_id)
    rows = await session.scalars(
        select(OrganizationMember)
        .where(OrganizationMember.organization_id == organization_id)
        .order_by(OrganizationMember.created_at)
    )
    return [_out(m) for m in rows]


async def _get_member(
    session: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID
) -> OrganizationMember:
    member = await session.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
        )
    )
    if member is None:
        raise NotFoundError("Member not found.")
    return member


async def _admin_count(session: AsyncSession, organization_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(OrganizationMember)
            .join(RoleModel, RoleModel.id == OrganizationMember.role_id)
            .where(
                OrganizationMember.organization_id == organization_id,
                RoleModel.key == Role.ORG_ADMIN.value,
            )
        )
        or 0
    )


async def add_member(
    session: AsyncSession,
    principal: Principal,
    organization_id: uuid.UUID,
    email: str,
    role: Role,
    meta: RequestMeta,
) -> MemberOut:
    _check_org(principal, organization_id)
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        raise NotFoundError("No registered user with this email address.")
    exists = await session.scalar(
        select(OrganizationMember.id).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user.id,
        )
    )
    if exists is not None:
        raise ConflictError("This user is already a member.")
    member = OrganizationMember(
        organization_id=organization_id, user_id=user.id, role_id=await role_id(session, role)
    )
    session.add(member)
    await session.flush()
    await session.refresh(member)
    await audit.record(
        session,
        "member.add",
        organization_id=organization_id,
        actor_user_id=principal.user_id,
        resource_type="user",
        resource_id=user.id,
        meta=meta,
        metadata={"role": role.value},
    )
    return _out(member)


async def change_role(
    session: AsyncSession,
    principal: Principal,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    role: Role,
    meta: RequestMeta,
) -> MemberOut:
    _check_org(principal, organization_id)
    member = await _get_member(session, organization_id, user_id)
    previous = member.role.key
    if (
        previous == Role.ORG_ADMIN.value
        and role != Role.ORG_ADMIN
        and await _admin_count(session, organization_id) <= 1
    ):
        raise ConflictError("The organization must keep at least one Organization Admin.")
    member.role_id = await role_id(session, role)
    await session.flush()
    await session.refresh(member, attribute_names=["role"])
    await audit.record(
        session,
        "member.role_change",
        organization_id=organization_id,
        actor_user_id=principal.user_id,
        resource_type="user",
        resource_id=user_id,
        meta=meta,
        metadata={"from": previous, "to": role.value},
    )
    return _out(member)


async def remove_member(
    session: AsyncSession,
    principal: Principal,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    meta: RequestMeta,
) -> None:
    _check_org(principal, organization_id)
    member = await _get_member(session, organization_id, user_id)
    if (
        member.role.key == Role.ORG_ADMIN.value
        and await _admin_count(session, organization_id) <= 1
    ):
        raise ConflictError("The organization must keep at least one Organization Admin.")
    await session.delete(member)
    # Removing access also ends the member's sessions in this organization.
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.organization_id == organization_id,
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await audit.record(
        session,
        "member.remove",
        organization_id=organization_id,
        actor_user_id=principal.user_id,
        resource_type="user",
        resource_id=user_id,
        meta=meta,
    )
