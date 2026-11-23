"""Start a comparison job for a case (the worker runs persist.run_comparison)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job
from app.services.audit import service as audit
from app.services.cases.service import get_case
from app.services.identity.principal import Principal, RequestMeta
from app.services.jobs.service import create_job

COMPARE_KIND = "case.compare"


async def start_comparison(
    session: AsyncSession, principal: Principal, case_id: uuid.UUID, meta: RequestMeta
) -> Job:
    await get_case(session, principal.organization_id, case_id)
    job = await create_job(
        session,
        principal.organization_id,
        COMPARE_KIND,
        payload={"case_id": str(case_id)},
        created_by=principal.user_id,
        max_attempts=2,
    )
    await audit.record(
        session,
        "case.compare",
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        resource_type="case",
        resource_id=case_id,
        meta=meta,
        metadata={"job_id": str(job.id)},
    )
    return job
