# Req: authentication-rbac 1.4, 3.1, 3.2
from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)


def test_access_token_round_trip(settings_env: None) -> None:
    user, org = uuid.uuid4(), uuid.uuid4()
    token, expires_in = create_access_token(user, org, "investigator")
    claims = decode_access_token(token)
    assert (claims.user_id, claims.organization_id, claims.role) == (user, org, "investigator")
    assert expires_in == 15 * 60


def test_expired_token_rejected(settings_env: None) -> None:
    token, _ = create_access_token(
        uuid.uuid4(), uuid.uuid4(), "reviewer", now=datetime.now(UTC) - timedelta(hours=1)
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_tampered_signature_rejected(settings_env: None) -> None:
    token, _ = create_access_token(uuid.uuid4(), uuid.uuid4(), "reviewer")
    header, payload, sig = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    claims["role"] = "org_admin"
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    with pytest.raises(InvalidTokenError):
        decode_access_token(f"{header}.{forged}.{sig}")


def test_alg_none_rejected(settings_env: None) -> None:
    now = int(datetime.now(UTC).timestamp())
    unsigned = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "org": str(uuid.uuid4()),
            "type": "access",
            "jti": "x",
            "iat": now,
            "exp": now + 600,
        },
        key=None,
        algorithm="none",
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(unsigned)


def test_algorithm_confusion_header_rejected(settings_env: None) -> None:
    # A valid HS256 token whose header claims RS256 must not be accepted under any algorithm.
    token, _ = create_access_token(uuid.uuid4(), uuid.uuid4(), "reviewer")
    _, payload, sig = token.split(".")
    rs_header = base64.urlsafe_b64encode(b'{"alg":"RS256","typ":"JWT"}').rstrip(b"=").decode()
    with pytest.raises(InvalidTokenError):
        decode_access_token(f"{rs_header}.{payload}.{sig}")


def test_wrong_secret_and_wrong_type_rejected(settings_env: None) -> None:
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "sub": str(uuid.uuid4()),
        "org": str(uuid.uuid4()),
        "jti": "x",
        "iat": now,
        "exp": now + 600,
    }
    other_key = jwt.encode(
        {**claims, "type": "access"}, "another-secret-of-32-characters!!", algorithm="HS256"
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(other_key)
    from app.core.config import get_settings

    refresh_typed = jwt.encode(
        {**claims, "type": "refresh"}, get_settings().jwt_secret, algorithm="HS256"
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(refresh_typed)


def test_password_hash_is_argon2id_and_verifies() -> None:
    hashed = hash_password("a-long-password-123")
    assert hashed.startswith("$argon2id$")
    assert verify_password("a-long-password-123", hashed)
    assert not verify_password("a-long-password-124", hashed)
    assert not verify_password("anything", "not-a-hash")


def test_refresh_tokens_are_random_and_hashed() -> None:
    tokens = {new_refresh_token() for _ in range(200)}
    assert len(tokens) == 200
    t = next(iter(tokens))
    assert len(hash_refresh_token(t)) == 64 and hash_refresh_token(t) != t
