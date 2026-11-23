# Req: platform-foundation 4.1, 4.2, 4.4
from __future__ import annotations

import asyncio

import asyncpg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Base
from tests.integration.conftest import (
    TestDatabase,
    alembic_config,
    create_temp_database,
    drop_temp_database,
)

pytestmark = pytest.mark.integration


def _diff(url: str) -> list[object]:
    async def run() -> list[object]:
        engine = create_async_engine(url, poolclass=NullPool)
        async with engine.connect() as conn:
            diff = await conn.run_sync(
                lambda c: compare_metadata(MigrationContext.configure(c), Base.metadata)
            )
        await engine.dispose()
        return list(diff)

    return asyncio.run(run())


def _tables(url: str) -> set[str]:
    async def run() -> set[str]:
        conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
        try:
            rows = await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                "AND tablename <> 'alembic_version'"
            )
        finally:
            await conn.close()
        return {r["tablename"] for r in rows}

    return asyncio.run(run())


def test_upgrade_downgrade_upgrade_cycle_and_no_drift(test_db: TestDatabase) -> None:
    db = create_temp_database("veritas_migcycle")
    try:
        cfg = alembic_config(db.owner_url)
        command.upgrade(cfg, "head")
        assert {"organizations", "users", "audit_logs", "jobs"} <= _tables(db.owner_url)
        command.downgrade(cfg, "base")
        assert _tables(db.owner_url) == set()
        command.upgrade(cfg, "head")
        assert _diff(db.owner_url) == []
    finally:
        drop_temp_database(db)
