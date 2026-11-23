"""Request dependencies: authentication, tenant context and permission checks."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session, set_tenant
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.logging import org_id_var
from app.core.permissions import permissions_for
from app.core.security import InvalidTokenError, decode_access_token
from app.models import OrganizationMember
from app.services.identity.principal import Principal, RequestMeta

_bearer = HTTPBearer(auto_error=False, description="Access token from /auth/login")
_UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}


def request_meta(request: Request) -> RequestMeta:
    return RequestMeta(
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


async def db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


async def get_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(db_session),
) -> Principal:
    """Validate the access token, bind the transaction to its organization (RLS),
    and re-check the membership and role from the database on every request."""
    if creds is None or creds.scheme.lower() != "bearer":
        raise AuthenticationError("Missing bearer token.", headers=_UNAUTHORIZED)
    try:
        claims = decode_access_token(creds.credentials)
    except InvalidTokenError as exc:
        raise AuthenticationError("Invalid or expired token.", headers=_UNAUTHORIZED) from exc

    await set_tenant(session, claims.organization_id)
    member = await session.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == claims.organization_id,
            OrganizationMember.user_id == claims.user_id,
        )
    )
    if member is None or not member.user.is_active:
        raise AuthenticationError("Invalid or expired token.", headers=_UNAUTHORIZED)
    org_id_var.set(str(claims.organization_id))
    role = member.role.key
    return Principal(
        user_id=claims.user_id,
        organization_id=claims.organization_id,
        role=role,
        permissions=permissions_for(role),
    )


def require_permission(permission: str) -> Callable[..., Awaitable[Principal]]:
    async def _check(principal: Principal = Depends(get_principal)) -> Principal:
        if permission not in principal.permissions:
            raise PermissionDeniedError(f"Your role does not allow '{permission}'.")
        return principal

    _check.__name__ = f"require_{permission.replace(':', '_')}"
    return _check
