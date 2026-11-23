# Req: platform-foundation 5.2 (event sequence numbers strictly increase, persisted)
from __future__ import annotations

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select

from app.core.db import tenant_session
from app.models import JobEvent, JobStatus
from app.services.jobs import service as job_service
from tests.integration.conftest import register

pytestmark = pytest.mark.integration

statuses = st.sampled_from(list(JobStatus))


@settings(
    max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(walk=st.lists(statuses, min_size=0, max_size=12))
async def test_persisted_event_seq_is_gapless_and_increasing(
    client: httpx.AsyncClient, walk: list[JobStatus]
) -> None:
    acct = await register(client)
    async with tenant_session(acct.organization_id) as s:
        job = await job_service.create_job(s, acct.organization_id, "prop.job")
        for target in walk:
            if job_service.can_transition(job.status, target):
                await job_service.transition(s, job, target)
            else:
                with pytest.raises(job_service.InvalidTransitionError):
                    await job_service.transition(s, job, target)
        seqs = list(
            await s.scalars(
                select(JobEvent.seq).where(JobEvent.job_id == job.id).order_by(JobEvent.id)
            )
        )
    assert seqs == list(range(1, len(seqs) + 1))
