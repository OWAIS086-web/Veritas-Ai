"""Organization and membership schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field, field_validator

from app.core.permissions import Role
from app.schemas.common import ApiModel


class OrganizationCreate(ApiModel):
    name: str = Field(min_length=2, max_length=200)


class OrganizationUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    retention_days: int | None = Field(default=None, ge=1, le=3650)


class MyOrganizationOut(ApiModel):
    id: uuid.UUID
    name: str
    slug: str
    role: Role
    joined_at: datetime


class MemberOut(ApiModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: Role
    created_at: datetime


class MemberAdd(ApiModel):
    email: EmailStr
    role: Role

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.strip().lower()


class MemberRoleUpdate(ApiModel):
    role: Role
