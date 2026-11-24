"""Object storage interface and server-side key generation.

Keys are always built here from ids, never from user input:
    {organization_id}/{document_id}/original
    {organization_id}/{document_id}/derived/{artifact}
"""

from __future__ import annotations

import re
import uuid
from typing import Protocol

_ARTIFACT = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")
_KEY = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/"
    r"(original|derived/[a-z0-9][a-z0-9._-]{0,80})$"
)


_PREFIX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/$"
)


class ObjectExistsError(Exception):
    """put_new refused to overwrite an existing object (originals are immutable)."""


class ObjectNotFoundError(Exception):
    pass


def original_key(organization_id: uuid.UUID, document_id: uuid.UUID) -> str:
    return f"{organization_id}/{document_id}/original"


def derived_key(organization_id: uuid.UUID, document_id: uuid.UUID, artifact: str) -> str:
    if not _ARTIFACT.match(artifact):
        raise ValueError(f"invalid artifact name: {artifact!r}")
    return f"{organization_id}/{document_id}/derived/{artifact}"


def resource_prefix(organization_id: uuid.UUID, resource_id: uuid.UUID) -> str:
    """Every object of one document, report or comparison: `{org}/{id}/`."""
    return f"{uuid.UUID(str(organization_id))}/{uuid.UUID(str(resource_id))}/"


def validate_prefix(prefix: str) -> str:
    if not _PREFIX.match(prefix):
        raise ValueError("invalid storage prefix")
    return prefix


def validate_key(key: str) -> str:
    if not _KEY.match(key):
        raise ValueError("invalid storage key")
    return key


def key_organization(key: str) -> uuid.UUID:
    return uuid.UUID(validate_key(key).split("/", 1)[0])


class ObjectStore(Protocol):
    async def put_new(self, key: str, data: bytes, content_type: str) -> None:
        """Write an object that must not already exist."""

    async def put_derived(self, key: str, data: bytes, content_type: str) -> None:
        """Write or replace a derived artifact (never an original)."""

    async def get(self, key: str) -> bytes: ...

    async def exists(self, key: str) -> bool: ...

    async def ping(self) -> None:
        """Health check: raises if the store can't be reached."""

    async def delete_prefix(self, prefix: str) -> int:
        """Delete every object under `{organization_id}/{resource_id}/` (retention purge only).
        Returns the number of objects deleted."""
        ...
