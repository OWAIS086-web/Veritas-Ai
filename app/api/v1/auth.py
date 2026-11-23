"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, get_principal, request_meta
from app.core.redis import get_redis
from app.schemas.auth import LoginRequest, MeResponse, RefreshRequest, RegisterRequest, TokenPair
from app.schemas.common import Problem
from app.services.identity import auth as auth_service
from app.services.identity.principal import Principal, RequestMeta

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=TokenPair,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": Problem}},
    summary="Create a user and a new organization (caller becomes Organization Admin)",
)
async def register(
    body: RegisterRequest,
    session: AsyncSession = Depends(db_session),
    meta: RequestMeta = Depends(request_meta),
) -> TokenPair:
    return await auth_service.register(session, body, meta)


@router.post(
    "/login",
    response_model=TokenPair,
    responses={401: {"model": Problem}, 429: {"model": Problem}, 503: {"model": Problem}},
    summary="Exchange email and password for an access and refresh token pair",
)
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(db_session),
    meta: RequestMeta = Depends(request_meta),
) -> TokenPair:
    return await auth_service.login(session, get_redis(), body, meta)


@router.post(
    "/refresh",
    response_model=TokenPair,
    responses={401: {"model": Problem}},
    summary="Rotate a refresh token (reuse of an old token revokes the whole session family)",
)
async def refresh(
    body: RefreshRequest,
    session: AsyncSession = Depends(db_session),
    meta: RequestMeta = Depends(request_meta),
) -> TokenPair:
    return await auth_service.refresh(session, body.refresh_token, meta)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke the refresh token's session family",
)
async def logout(
    body: RefreshRequest,
    session: AsyncSession = Depends(db_session),
    meta: RequestMeta = Depends(request_meta),
) -> Response:
    await auth_service.logout(session, body.refresh_token, meta)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    response_model=MeResponse,
    responses={401: {"model": Problem}},
    summary="The current user, active organization, role and permissions",
)
async def me(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(db_session),
) -> MeResponse:
    return await auth_service.me(session, principal)
