"""Shared API schema pieces."""

from __future__ import annotations

import base64
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import ValidationFailedError


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


class Problem(BaseModel):
    """RFC 7807 problem details (documented for OpenAPI)."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str | None = None
    request_id: str | None = None


PageLimit = Field(default=50, ge=1, le=100, description="Page size (max 100)")


def encode_cursor(*parts: object) -> str:
    """Opaque, URL-safe cursor (timestamps contain '+', which breaks raw query strings)."""
    raw = "|".join(p.isoformat() if isinstance(p, datetime) else str(p) for p in parts)
    return base64.urlsafe_b64encode(raw.encode()).rstrip(b"=").decode()


def decode_cursor(cursor: str, count: int) -> list[str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationFailedError("Invalid pagination cursor.") from exc
    parts = raw.split("|")
    if len(parts) != count:
        raise ValidationFailedError("Invalid pagination cursor.")
    return parts


PROBLEM_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": Problem, "description": "Missing or invalid credentials"},
    403: {"model": Problem, "description": "Role lacks the required permission"},
    404: {"model": Problem, "description": "Not found (or belongs to another organization)"},
}
