"""Authentication request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field, field_validator

from app.core.permissions import Role
from app.schemas.common import ApiModel


def _normalize_email(value: str) -> str:
    return value.strip().lower()


class RegisterRequest(ApiModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    organization_name: str = Field(min_length=2, max_length=200)

    _email = field_validator("email")(_normalize_email)


class LoginRequest(ApiModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    organization_id: uuid.UUID | None = None

    _email = field_validator("email")(_normalize_email)


class RefreshRequest(ApiModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class TokenPair(ApiModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105  (OAuth token type label, not a secret)
    expires_in: int


class UserOut(ApiModel):
    id: uuid.UUID
    email: str
    full_name: str
    created_at: datetime


class OrganizationOut(ApiModel):
    id: uuid.UUID
    name: str
    slug: str
    retention_days: int | None
    created_at: datetime


class MeResponse(ApiModel):
    user: UserOut
    organization: OrganizationOut
    role: Role
    permissions: list[str]
