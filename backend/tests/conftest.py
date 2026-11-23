"""Shared fixtures for unit and property tests (no infrastructure needed)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture
def settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Minimal valid settings without touching real infrastructure."""
    from app.core.config import get_settings

    monkeypatch.setenv("VERITAS_DATABASE_URL", "postgresql+asyncpg://u:p@127.0.0.1:1/x")
    monkeypatch.setenv("VERITAS_REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("VERITAS_JWT_SECRET", "unit-test-secret-0123456789abcdef")
    monkeypatch.setenv("VERITAS_ACCESS_TOKEN_MINUTES", "15")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
