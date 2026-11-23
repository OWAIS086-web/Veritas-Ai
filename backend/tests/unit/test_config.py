# Req: platform-foundation 1.1-1.3
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings

BASE = {
    "database_url": "postgresql+asyncpg://u:p@h/db",
    "redis_url": "redis://h:6379/0",
    "jwt_secret": "x" * 40,
}


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def test_valid_settings() -> None:
    s = _settings(cors_origins="http://a, http://b ,")
    assert s.cors_origin_list == ["http://a", "http://b"]
    assert s.broker_url == "redis://h:6379/0"


@pytest.mark.parametrize("missing", ["database_url", "redis_url", "jwt_secret"])
def test_missing_required_setting_fails(missing: str, monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("VERITAS_DATABASE_URL", "VERITAS_REDIS_URL", "VERITAS_JWT_SECRET"):
        monkeypatch.delenv(key, raising=False)
    values = {k: v for k, v in BASE.items() if k != missing}
    with pytest.raises(ValidationError) as info:
        Settings(_env_file=None, **values)  # type: ignore[arg-type]
    assert missing in str(info.value)


def test_sync_database_driver_rejected() -> None:
    with pytest.raises(ValidationError, match="asyncpg"):
        _settings(database_url="postgresql://u:p@h/db")


@pytest.mark.parametrize("secret", ["CHANGE_ME_generate_a_long_random_secret", "short-but-16chars"])
def test_production_rejects_weak_secrets(secret: str) -> None:
    with pytest.raises(ValidationError):
        _settings(env="production", jwt_secret=secret)


def test_any_env_rejects_tiny_secret() -> None:
    with pytest.raises(ValidationError):
        _settings(jwt_secret="tiny")


def test_secret_not_in_repr() -> None:
    assert "x" * 40 not in repr(_settings())
