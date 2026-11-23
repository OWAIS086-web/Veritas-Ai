"""Organization and membership endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, get_principal, request_meta, require_permission
from app.schemas.auth import OrganizationOut
from app.schemas.common import PROBLEM_RESPONSES, Problem
from app.schemas.organizations import (
    MemberAdd,
    MemberOut,
    MemberRoleUpdate,
    MyOrganizationOut,
    OrganizationCreate,
    OrganizationUpdate,
)
from app.services.identity import members as member_service
from app.services.identity import organizations as org_service
from app.services.identity.principal import Principal, RequestMeta

router = APIRouter(prefix="/organizations", tags=["organizations"], responses=PROBLEM_RESPONSES)


@router.get(
    "", response_model=list[MyOrganizationOut], summary="Organizations the caller belongs to"
)
async def list_organizations(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(db_session),
) -> list[MyOrganizationOut]:
    return await org_service.list_mine(session, principal.user_id)


@router.post(
    "",
    response_model=OrganizationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an organization with the caller as Organization Admin",
)
async def create_organization(
    body: OrganizationCreate,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(db_session),
    meta: RequestMeta = Depends(request_meta),
) -> OrganizationOut:
    return await org_service.create(session, principal, body.name, meta)


@router.get(
    "/{organization_id}",
    response_model=OrganizationOut,
    summary="The active organization (other ids return 404)",
)
async def get_organization(
    organization_id: uuid.UUID,
    principal: Principal = Depends(require_permission("org:read")),
    session: AsyncSession = Depends(db_session),
) -> OrganizationOut:
    return await org_service.get(session, principal, organization_id)


@router.patch(
    "/{organization_id}",
    response_model=OrganizationOut,
    summary="Update the active organization's name or retention",
)
async def update_organization(
    organization_id: uuid.UUID,
    body: OrganizationUpdate,
    principal: Principal = Depends(require_permission("org:update")),
    session: AsyncSession = Depends(db_session),
    meta: RequestMeta = Depends(request_meta),
) -> OrganizationOut:
    return await org_service.update(session, principal, organization_id, body, meta)


@router.get(
    "/{organization_id}/members",
    response_model=list[MemberOut],
    summary="Members of the active organization",
)
async def list_members(
    organization_id: uuid.UUID,
    principal: Principal = Depends(require_permission("members:read")),
    session: AsyncSession = Depends(db_session),
) -> list[MemberOut]:
    return await member_service.list_members(session, principal, organization_id)


@router.post(
    "/{organization_id}/members",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": Problem}},
    summary="Add an existing user to the organization with a role",
)
async def add_member(
    organization_id: uuid.UUID,
    body: MemberAdd,
    principal: Principal = Depends(require_permission("members:manage")),
    session: AsyncSession = Depends(db_session),
    meta: RequestMeta = Depends(request_meta),
) -> MemberOut:
    return await member_service.add_member(
        session, principal, organization_id, body.email, body.role, meta
    )


@router.patch(
    "/{organization_id}/members/{user_id}",
    response_model=MemberOut,
    responses={409: {"model": Problem}},
    summary="Change a member's role",
)
async def change_member_role(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberRoleUpdate,
    principal: Principal = Depends(require_permission("members:manage")),
    session: AsyncSession = Depends(db_session),
    meta: RequestMeta = Depends(request_meta),
) -> MemberOut:
    return await member_service.change_role(
        session, principal, organization_id, user_id, body.role, meta
    )


@router.delete(
    "/{organization_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"model": Problem}},
    summary="Remove a member and revoke their sessions in this organization",
)
async def remove_member(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    principal: Principal = Depends(require_permission("members:manage")),
    session: AsyncSession = Depends(db_session),
    meta: RequestMeta = Depends(request_meta),
) -> Response:
    await member_service.remove_member(session, principal, organization_id, user_id, meta)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
