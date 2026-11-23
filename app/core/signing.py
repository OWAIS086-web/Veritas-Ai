"""Short-lived HMAC-signed file access tokens.

token = base64url(document_id|organization_id|expires_unix|artifact) "." base64url(hmac_sha256)
`artifact` is "original" or a derived artifact name (e.g. "page-0001.png"). The key is derived
from the JWT secret with a fixed context label, so a file token can never be used as an access
token and vice versa.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
import uuid
from dataclasses import dataclass

from app.core.config import get_settings

_ARTIFACT = re.compile(r"^(original|[a-z0-9][a-z0-9._-]{0,80})$")


class InvalidSignatureError(Exception):
    pass


@dataclass(frozen=True)
class FileGrant:
    document_id: uuid.UUID
    organization_id: uuid.UUID
    expires_at: int
    artifact: str = "original"


def _key() -> bytes:
    secret = get_settings().jwt_secret.encode("utf-8")
    return hmac.new(secret, b"veritas-file-signing-v1", hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(
    document_id: uuid.UUID,
    organization_id: uuid.UUID,
    ttl_seconds: int,
    now: float | None = None,
    artifact: str = "original",
) -> tuple[str, int]:
    if not _ARTIFACT.match(artifact):
        raise ValueError("invalid artifact name")
    expires = int((now if now is not None else time.time()) + ttl_seconds)
    body = f"{document_id}|{organization_id}|{expires}|{artifact}".encode()
    mac = hmac.new(_key(), body, hashlib.sha256).digest()
    return f"{_b64(body)}.{_b64(mac)}", expires


def verify(token: str, now: float | None = None) -> FileGrant:
    try:
        body_part, mac_part = token.split(".", 1)
        body = _unb64(body_part)
        mac = _unb64(mac_part)
    except (ValueError, TypeError) as exc:
        raise InvalidSignatureError("malformed token") from exc
    expected = hmac.new(_key(), body, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise InvalidSignatureError("bad signature")
    try:
        doc, org, exp, artifact = body.decode("utf-8").split("|")
        grant = FileGrant(uuid.UUID(doc), uuid.UUID(org), int(exp), artifact)
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidSignatureError("malformed body") from exc
    if not _ARTIFACT.match(grant.artifact):
        raise InvalidSignatureError("bad artifact")
    if grant.expires_at < (now if now is not None else time.time()):
        raise InvalidSignatureError("expired")
    return grant
