"""Integration fixtures: a throwaway database migrated with Alembic, the app connected as
the real non-owner role (so RLS applies), and Redis db 15.

Needs the Docker Postgres and Redis containers. Without them the integration tests are skipped
with an explicit reason, and the quality gate reports the skip as a failure.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from migrations.settings import get_migration_settings

BACKEND = Path(__file__).resolve().parents[2]
TEST_RATE_LIMIT = 5


@dataclass(frozen=True)
class TestDatabase:
    name: str
    owner_url: str  # postgresql+asyncpg:// as the owner
    app_url: str  # postgresql+asyncpg:// as veritas_app


def _plain(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _admin_exec(maintenance_url: str, sql: str) -> None:
    conn = await asyncpg.connect(_plain(maintenance_url), timeout=5)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.attributes["database_url"] = url
    cfg.attributes["configure_logger"] = False
    return cfg


def _app_password() -> str:
    value = os.environ.get("VERITAS_APP_DB_PASSWORD")
    if value:
        return value
    env_file = BACKEND.parent / ".env"
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("VERITAS_APP_DB_PASSWORD="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("VERITAS_APP_DB_PASSWORD is not configured")


def create_temp_database(prefix: str = "veritas_test") -> TestDatabase:
    settings = get_migration_settings()
    base = make_url(settings.migration_database_url)
    name = f"{prefix}_{secrets.token_hex(4)}"
    asyncio.run(_admin_exec(settings.migration_database_url, f'CREATE DATABASE "{name}"'))
    owner_url = base.set(database=name).render_as_string(hide_password=False)
    app_url = base.set(
        database=name, username=settings.app_db_user, password=_app_password()
    ).render_as_string(hide_password=False)
    return TestDatabase(name=name, owner_url=owner_url, app_url=app_url)


def drop_temp_database(db: TestDatabase) -> None:
    settings = get_migration_settings()
    asyncio.run(
        _admin_exec(
            settings.migration_database_url, f'DROP DATABASE IF EXISTS "{db.name}" WITH (FORCE)'
        )
    )


@pytest.fixture(scope="session")
def test_db() -> Iterator[TestDatabase]:
    try:
        db = create_temp_database()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL unavailable for integration tests: {type(exc).__name__}: {exc}")
    try:
        command.upgrade(alembic_config(db.owner_url), "head")
        yield db
    finally:
        drop_temp_database(db)


@pytest.fixture(scope="session")
def app_env(test_db: TestDatabase) -> Iterator[None]:
    """Point the application settings at the test database and Redis db 15."""
    overrides = {
        "VERITAS_ENV": "test",
        "VERITAS_DATABASE_URL": test_db.app_url,
        # The production pool: a new connection per session exhausted Windows socket
        # buffers (WinError 10055) once the suite grew. The tenant setting is
        # transaction-local, so pooled connections can't carry it between tests.
        "VERITAS_DB_NULL_POOL": "false",
        "VERITAS_REDIS_URL": "redis://127.0.0.1:6379/15",
        "VERITAS_LOGIN_RATE_LIMIT_PER_MINUTE": str(TEST_RATE_LIMIT),
        "VERITAS_JWT_SECRET": "test-secret-" + secrets.token_hex(16),
        "VERITAS_STORAGE_ENDPOINT": "127.0.0.1:9000",
        "VERITAS_STORAGE_BUCKET": "veritas-test-" + secrets.token_hex(4),
        # The pipeline under test is the deterministic one; provider tests use recordings.
        "VERITAS_LLM_BASE_URL": "",
        "VERITAS_STAGE_MAX_ATTEMPTS": "2",
        # A namespace of its own, so tests never see or remove the running stack's graphs.
        "VERITAS_NEO4J_URI": "bolt://127.0.0.1:7687",
        "VERITAS_NEO4J_NAMESPACE": "test-" + secrets.token_hex(4),
    }
    previous = {k: os.environ.get(k) for k in overrides}
    os.environ.update(overrides)
    _clear_caches()
    import redis

    try:
        redis.Redis.from_url(overrides["VERITAS_REDIS_URL"], socket_connect_timeout=2).flushdb()
    except redis.exceptions.RedisError as exc:  # pragma: no cover
        pytest.skip(f"Redis unavailable for integration tests: {exc}")
    yield
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    _clear_caches()


def _clear_caches() -> None:
    from app.core.config import get_settings
    from app.core.db import get_engine, get_sessionmaker
    from app.core.redis import get_redis
    from app.integrations.graph.neo4j_store import get_store as get_graph_store
    from app.integrations.storage.s3_store import get_store

    for fn in (get_settings, get_engine, get_sessionmaker, get_redis, get_store, get_graph_store):
        fn.cache_clear()


@pytest.fixture(scope="session")
def app(app_env: None) -> Any:
    from app.main import create_app

    return create_app()


def _random_ip() -> str:
    return f"10.{secrets.randbelow(255)}.{secrets.randbelow(255)}.{secrets.randbelow(254) + 1}"


@pytest.fixture
async def client(app: Any) -> AsyncIterator[httpx.AsyncClient]:
    # A distinct client IP per test keeps the per-IP login rate limit independent.
    transport = httpx.ASGITransport(app=app, client=(_random_ip(), 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@dataclass
class Account:
    email: str
    password: str
    access: str
    refresh: str
    organization_id: uuid.UUID
    user_id: uuid.UUID

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access}"}


def unique_email(tag: str = "user") -> str:
    return f"{tag}-{secrets.token_hex(5)}@example.com"


async def register(
    client: httpx.AsyncClient, org_name: str = "Acme Imports", email: str | None = None
) -> Account:
    email = email or unique_email()
    password = "correct-horse-" + secrets.token_hex(4)
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Test User",
            "organization_name": org_name,
        },
    )
    assert resp.status_code == 201, resp.text
    tokens = resp.json()
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200, me.text
    body = me.json()
    return Account(
        email=email,
        password=password,
        access=tokens["access_token"],
        refresh=tokens["refresh_token"],
        organization_id=uuid.UUID(body["organization"]["id"]),
        user_id=uuid.UUID(body["user"]["id"]),
    )


async def login(
    client: httpx.AsyncClient, account: Account, organization_id: uuid.UUID | None = None
) -> Account:
    payload: dict[str, Any] = {"email": account.email, "password": account.password}
    if organization_id:
        payload["organization_id"] = str(organization_id)
    resp = await client.post("/api/v1/auth/login", json=payload)
    assert resp.status_code == 200, resp.text
    tokens = resp.json()
    return Account(
        email=account.email,
        password=account.password,
        access=tokens["access_token"],
        refresh=tokens["refresh_token"],
        organization_id=organization_id or account.organization_id,
        user_id=account.user_id,
    )


@pytest.fixture(autouse=True)
def no_broker(monkeypatch: pytest.MonkeyPatch) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """The broker hand-off is recorded instead of sent; pipeline tests run it in-process."""
    import app.api.v1.cases as cases_api
    import app.api.v1.documents as documents_api
    import app.api.v1.findings as findings_api
    import app.api.v1.graph as graph_api

    sent: list[tuple[uuid.UUID, uuid.UUID]] = []
    monkeypatch.setattr(cases_api, "enqueue_processing", lambda o, j: sent.append((o, j)))
    monkeypatch.setattr(documents_api, "enqueue_processing", lambda o, j: sent.append((o, j)))
    monkeypatch.setattr(findings_api, "enqueue_comparison", lambda o, j: sent.append((o, j)))
    monkeypatch.setattr(graph_api, "enqueue_graph_sync", lambda: None)
    return sent
