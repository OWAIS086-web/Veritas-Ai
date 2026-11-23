# Req: platform-foundation 5.x, 6.x
from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.system import job_event_stream
from app.core.db import tenant_session
from app.models import Job
from app.services.jobs import service as job_service
from app.services.jobs.runner import Outcome, execute_job
from app.workers.system_tasks import ping_work
from tests.integration.conftest import Account, register

pytestmark = pytest.mark.integration


async def _new_job(acct: Account, max_attempts: int = 3) -> uuid.UUID:
    async with tenant_session(acct.organization_id) as s:
        job = await job_service.create_job(
            s, acct.organization_id, "test.job", max_attempts=max_attempts
        )
        return job.id


async def _job(acct: Account, job_id: uuid.UUID) -> Job:
    async with tenant_session(acct.organization_id) as s:
        return await job_service.get_job(s, acct.organization_id, job_id)


async def test_ping_job_succeeds_through_runner(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    job_id = await _new_job(acct)
    result = await execute_job(acct.organization_id, job_id, ping_work)
    assert result.outcome is Outcome.SUCCEEDED
    job = await _job(acct, job_id)
    assert job.status == "succeeded" and job.progress == 100 and job.attempts == 1
    assert job.result is not None and "db_roundtrip_ms" in job.result

    # Idempotent re-delivery: a terminal job is skipped and keeps its single attempt.
    again = await execute_job(acct.organization_id, job_id, ping_work)
    assert again.outcome is Outcome.SKIPPED
    assert (await _job(acct, job_id)).attempts == 1


async def test_failing_job_retries_then_fails_after_max_attempts(
    client: httpx.AsyncClient,
) -> None:
    acct = await register(client)
    job_id = await _new_job(acct, max_attempts=3)

    async def boom(session: AsyncSession, job: Job) -> dict[str, Any]:
        raise RuntimeError("simulated failure")

    outcomes = [await execute_job(acct.organization_id, job_id, boom) for _ in range(4)]
    assert [o.outcome for o in outcomes] == [
        Outcome.RETRY,
        Outcome.RETRY,
        Outcome.FAILED,
        Outcome.SKIPPED,
    ]
    assert outcomes[0].retry_in_seconds == 2 and outcomes[1].retry_in_seconds == 4
    job = await _job(acct, job_id)
    assert job.status == "failed" and job.attempts == 3
    assert job.error is not None and "simulated failure" in job.error


async def test_failed_work_rolls_back_its_writes(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    job_id = await _new_job(acct, max_attempts=1)

    async def partial(session: AsyncSession, job: Job) -> dict[str, Any]:
        job.payload = {"half": "written"}
        await session.flush()
        raise RuntimeError("after partial write")

    await execute_job(acct.organization_id, job_id, partial)
    assert (await _job(acct, job_id)).payload == {}


async def test_job_api_and_cross_org_404(client: httpx.AsyncClient) -> None:
    a = await register(client)
    b = await register(client)
    job_id = await _new_job(a)
    own = await client.get(f"/api/v1/jobs/{job_id}", headers=a.headers)
    assert own.status_code == 200 and own.json()["status"] == "queued"
    assert (await client.get(f"/api/v1/jobs/{job_id}", headers=b.headers)).status_code == 404
    assert (await client.get(f"/api/v1/jobs/{job_id}/events", headers=b.headers)).status_code == 404


async def test_ping_job_endpoint_persists_a_queued_job(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.v1.system as system_api

    enqueued: list[tuple[uuid.UUID, uuid.UUID]] = []
    # The broker hand-off is replaced only here; the worker path is tested via execute_job
    # above and end to end in the Docker smoke test.
    monkeypatch.setattr(system_api, "_enqueue_ping", lambda o, j: enqueued.append((o, j)))
    acct = await register(client)
    resp = await client.post("/api/v1/system/ping-job", headers=acct.headers)
    assert resp.status_code == 202
    job_id = uuid.UUID(resp.json()["id"])
    assert enqueued == [(acct.organization_id, job_id)]
    assert (await _job(acct, job_id)).status == "queued"


async def test_sse_stream_resumes_after_last_event_id(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    job_id = await _new_job(acct)
    await execute_job(acct.organization_id, job_id, ping_work)  # queued, started, succeeded

    async def collect(after: int) -> list[int]:
        seqs = []
        async for chunk in job_event_stream(acct.organization_id, job_id, after):
            if chunk.startswith("id: "):
                seqs.append(int(chunk.split("\n", 1)[0][4:]))
        return seqs

    assert await collect(0) == [1, 2, 3]
    assert await collect(2) == [3]
    assert await collect(3) == []

    resp = await client.get(
        f"/api/v1/jobs/{job_id}/events", headers={**acct.headers, "Last-Event-ID": "1"}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "id: 2" in resp.text and "id: 1\n" not in resp.text and "event: end" in resp.text


async def test_overview_stats_are_computed_from_records(client: httpx.AsyncClient) -> None:
    acct = await register(client)
    fresh = (await client.get("/api/v1/stats/overview", headers=acct.headers)).json()
    assert fresh["members"]["value"] == 1
    assert fresh["jobs_total"]["value"] == 0
    assert fresh["job_success_rate"]["value"] is None
    # Documents and cases exist since phase 2: computed from records (zero here).
    assert fresh["documents_processed"] == {"value": 0, "available": True, "note": None}
    assert fresh["active_investigations"] == {"value": 0, "available": True, "note": None}
    # Findings exist since phase 3: computed from records (zero here).
    assert fresh["findings_requiring_review"] == {"value": 0, "available": True, "note": None}
    assert fresh["high_priority_findings"] == {"value": 0, "available": True, "note": None}
    assert len(fresh["activity_14d"]) == 14
    assert fresh["activity_14d"][-1]["count"] >= 1  # the registration audit event

    ok = await _new_job(acct)
    await execute_job(acct.organization_id, ok, ping_work)
    bad = await _new_job(acct, max_attempts=1)

    async def boom(session: AsyncSession, job: Job) -> dict[str, Any]:
        raise RuntimeError("x")

    await execute_job(acct.organization_id, bad, boom)
    await _new_job(acct)

    after = (await client.get("/api/v1/stats/overview", headers=acct.headers)).json()
    assert after["jobs_total"]["value"] == 3
    assert after["jobs_failed"]["value"] == 1
    assert after["jobs_running"]["value"] == 1
    assert after["job_success_rate"]["value"] == 0.5

    other = await register(client)
    isolated = (await client.get("/api/v1/stats/overview", headers=other.headers)).json()
    assert isolated["jobs_total"]["value"] == 0
