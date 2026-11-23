"""Registration, login, refresh-token rotation, logout and the current user."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import set_tenant, tenant_session
from app.core.errors import AuthenticationError, ConflictError
from app.core.permissions import Role, permissions_for
from app.core.security import (
    burn_password_check,
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.models import Organization, OrganizationMember, RefreshToken, User
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    OrganizationOut,
    RegisterRequest,
    TokenPair,
    UserOut,
)
from app.services.audit import service as audit
from app.services.identity import organizations as org_service
from app.services.identity.principal import Principal, RequestMeta
from app.services.identity.rate_limit import check_login_rate

INVALID_CREDENTIALS = "Invalid email or password."
INVALID_REFRESH = "Invalid or expired refresh token."


async def _issue_pair(
    session: AsyncSession,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    role: str,
    family_id: uuid.UUID | None = None,
) -> tuple[TokenPair, RefreshToken]:
    """Create a refresh token row (tenant context must be set) and an access token."""
    settings = get_settings()
    raw = new_refresh_token()
    token = RefreshToken(
        id=uuid.uuid4(),
        organization_id=organization_id,
        user_id=user_id,
        family_id=family_id or uuid.uuid4(),
        token_hash=hash_refresh_token(raw),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
    )
    session.add(token)
    access, expires_in = create_access_token(user_id, organization_id, role)
    return TokenPair(access_token=access, refresh_token=raw, expires_in=expires_in), token


async def register(session: AsyncSession, req: RegisterRequest, meta: RequestMeta) -> TokenPair:
    existing = await session.scalar(select(User.id).where(User.email == req.email))
    if existing is not None:
        raise ConflictError("An account with this email already exists.")
    user = User(
        id=uuid.uuid4(),
        email=req.email,
        password_hash=hash_password(req.password),
        full_name=req.full_name.strip(),
        is_active=True,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("An account with this email already exists.") from exc
    org = await org_service.create_with_admin(session, req.organization_name, user.id)
    pair, _ = await _issue_pair(session, user.id, org.id, Role.ORG_ADMIN)
    await audit.record(
        session,
        "auth.register",
        organization_id=org.id,
        actor_user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        meta=meta,
    )
    return pair


async def _memberships(session: AsyncSession, user_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    rows = await session.execute(
        text("SELECT organization_id, role_key FROM auth_memberships(:uid)"), {"uid": user_id}
    )
    return [(r.organization_id, r.role_key) for r in rows]


async def login(
    session: AsyncSession, redis: Redis, req: LoginRequest, meta: RequestMeta
) -> TokenPair:
    settings = get_settings()
    await check_login_rate(redis, meta.ip, req.email, settings.login_rate_limit_per_minute)

    user = await session.scalar(select(User).where(User.email == req.email))
    if user is None:
        burn_password_check(req.password)
        await audit.record_independent(
            "auth.login_failed",
            organization_id=None,
            meta=meta,
            metadata={"reason": "invalid_credentials"},
        )
        raise AuthenticationError(INVALID_CREDENTIALS)

    memberships = await _memberships(session, user.id)
    password_ok = verify_password(req.password, user.password_hash)
    chosen = next((m for m in memberships if req.organization_id in (None, m[0])), None)
    if not password_ok or not user.is_active or chosen is None:
        await audit.record_independent(
            "auth.login_failed",
            organization_id=memberships[0][0] if memberships else None,
            actor_user_id=user.id,
            meta=meta,
            metadata={"reason": "invalid_credentials"},
        )
        raise AuthenticationError(INVALID_CREDENTIALS)

    organization_id, role = chosen
    await set_tenant(session, organization_id)
    pair, _ = await _issue_pair(session, user.id, organization_id, role)
    await audit.record(
        session,
        "auth.login",
        organization_id=organization_id,
        actor_user_id=user.id,
        meta=meta,
    )
    return pair


async def _find_refresh(session: AsyncSession, raw: str) -> RefreshTokenRow | None:
    row = (
        await session.execute(
            text("SELECT * FROM auth_find_refresh(:h)"), {"h": hash_refresh_token(raw)}
        )
    ).first()
    if row is None:
        return None
    return RefreshTokenRow(
        id=row.id,
        organization_id=row.organization_id,
        user_id=row.user_id,
        family_id=row.family_id,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )


class RefreshTokenRow:
    __slots__ = ("expires_at", "family_id", "id", "organization_id", "revoked_at", "user_id")

    def __init__(
        self,
        id: uuid.UUID,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        family_id: uuid.UUID,
        expires_at: datetime,
        revoked_at: datetime | None,
    ) -> None:
        self.id = id
        self.organization_id = organization_id
        self.user_id = user_id
        self.family_id = family_id
        self.expires_at = expires_at
        self.revoked_at = revoked_at


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def _handle_reuse(token: RefreshTokenRow, meta: RequestMeta) -> None:
    """A rotated token was presented again: assume theft and revoke the whole family.
    Runs in its own transaction because the request itself will fail."""
    async with tenant_session(token.organization_id) as s:
        await _revoke_family(s, token.family_id)
        await audit.record(
            s,
            "auth.refresh_reuse_detected",
            organization_id=token.organization_id,
            actor_user_id=token.user_id,
            meta=meta,
            metadata={"family_id": str(token.family_id)},
        )


async def refresh(session: AsyncSession, raw: str, meta: RequestMeta) -> TokenPair:
    token = await _find_refresh(session, raw)
    if token is None:
        raise AuthenticationError(INVALID_REFRESH)
    if token.revoked_at is not None:
        await _handle_reuse(token, meta)
        raise AuthenticationError(INVALID_REFRESH)
    if token.expires_at <= datetime.now(UTC):
        raise AuthenticationError(INVALID_REFRESH)

    await set_tenant(session, token.organization_id)
    member = await session.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == token.organization_id,
            OrganizationMember.user_id == token.user_id,
        )
    )
    if member is None or not member.user.is_active:
        await _revoke_family(session, token.family_id)
        raise AuthenticationError(INVALID_REFRESH)

    # Atomic claim: only one concurrent refresh can rotate this token.
    new_id = uuid.uuid4()
    claimed = await session.scalar(
        update(RefreshToken)
        .where(RefreshToken.id == token.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC), replaced_by_id=new_id)
        .returning(RefreshToken.id)
    )
    if claimed is None:
        await _handle_reuse(token, meta)
        raise AuthenticationError(INVALID_REFRESH)

    pair, new_token = await _issue_pair(
        session, token.user_id, token.organization_id, member.role.key, token.family_id
    )
    new_token.id = new_id
    return pair


async def logout(session: AsyncSession, raw: str, meta: RequestMeta) -> None:
    token = await _find_refresh(session, raw)
    if token is None:
        return  # same response whether or not the token existed
    await set_tenant(session, token.organization_id)
    await _revoke_family(session, token.family_id)
    await audit.record(
        session,
        "auth.logout",
        organization_id=token.organization_id,
        actor_user_id=token.user_id,
        meta=meta,
    )


async def me(session: AsyncSession, principal: Principal) -> MeResponse:
    user = await session.get(User, principal.user_id)
    org = await session.get(Organization, principal.organization_id)
    if user is None or org is None:
        raise AuthenticationError()
    return MeResponse(
        user=UserOut.model_validate(user),
        organization=OrganizationOut.model_validate(org),
        role=Role(principal.role),
        permissions=sorted(permissions_for(principal.role)),
    )
