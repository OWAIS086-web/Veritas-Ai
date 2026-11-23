"""Starting, reading, approving investigations and recording evidence requests.

Every query filters `organization_id` (RLS is the backstop). Ids of another organization or
of a deleted case are a 404.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.budget import Budget
from app.core.errors import ConflictError, NotFoundError
from app.models import (
    AgentEvent,
    AgentRun,
    Case,
    EvidenceRequest,
    Investigation,
    InvestigationStatus,
)
from app.schemas.investigations import (
    AgentEventOut,
    AgentRunOut,
    EvidenceRequestOut,
    InvestigationDetail,
    InvestigationOut,
)
from app.services.audit import service as audit
from app.services.cases.service import get_case
from app.services.identity.principal import Principal, RequestMeta

ACTIVE = (
    InvestigationStatus.QUEUED,
    InvestigationStatus.RUNNING,
    InvestigationStatus.AWAITING_REVIEW,
    InvestigationStatus.APPROVED,
)
STREAM_PAUSED = frozenset(
    {
        InvestigationStatus.AWAITING_REVIEW,
        InvestigationStatus.COMPLETED,
        InvestigationStatus.FAILED,
        InvestigationStatus.BUDGET_EXHAUSTED,
    }
)


async def get_investigation(
    s: AsyncSession, org: uuid.UUID, investigation_id: uuid.UUID, *, lock: bool = False
) -> Investigation:
    query = (
        select(Investigation)
        .join(Case, Case.id == Investigation.case_id)
        .where(
            Investigation.id == investigation_id,
            Investigation.organization_id == org,
            Case.deleted_at.is_(None),
        )
    )
    if lock:
        query = query.with_for_update(of=Investigation)
    inv = await s.scalar(query)
    if inv is None:
        raise NotFoundError("Investigation not found.")
    return inv


async def _event(
    s: AsyncSession, inv: Investigation, event_type: str, data: dict[str, object]
) -> None:
    seq = await s.scalar(
        update(Investigation)
        .where(Investigation.id == inv.id, Investigation.organization_id == inv.organization_id)
        .values(event_seq=Investigation.event_seq + 1)
        .returning(Investigation.event_seq)
    )
    s.add(
        AgentEvent(
            organization_id=inv.organization_id,
            investigation_id=inv.id,
            seq=seq,
            type=event_type,
            data=data,
        )
    )


async def start(
    s: AsyncSession,
    principal: Principal,
    case_id: uuid.UUID,
    objective: str,
    meta: RequestMeta,
) -> InvestigationOut:
    org = principal.organization_id
    case = await get_case(s, org, case_id)
    await s.execute(select(Case.id).where(Case.id == case.id).with_for_update())
    running = await s.scalar(
        select(Investigation.id).where(
            Investigation.organization_id == org,
            Investigation.case_id == case_id,
            Investigation.status.in_(ACTIVE),
        )
    )
    if running is not None:
        raise ConflictError("This case already has an investigation in progress.")
    inv = Investigation(
        id=uuid.uuid4(),
        organization_id=org,
        case_id=case_id,
        objective=objective.strip(),
        status=InvestigationStatus.QUEUED,
        budget=Budget.from_settings().limits(),
        usage={},
        result={},
        created_by=principal.user_id,
    )
    s.add(inv)
    await s.flush()
    await _event(s, inv, "queued", {"objective": inv.objective})
    await audit.record(
        s,
        "investigation.start",
        organization_id=org,
        actor_user_id=principal.user_id,
        resource_type="investigation",
        resource_id=inv.id,
        meta=meta,
        metadata={"case_id": str(case_id)},
    )
    return InvestigationOut.model_validate(inv)


async def list_for_case(
    s: AsyncSession, org: uuid.UUID, case_id: uuid.UUID
) -> list[InvestigationOut]:
    await get_case(s, org, case_id)
    rows = await s.scalars(
        select(Investigation)
        .where(Investigation.organization_id == org, Investigation.case_id == case_id)
        .order_by(Investigation.created_at.desc())
    )
    return [InvestigationOut.model_validate(r) for r in rows]


async def evidence_requests(
    s: AsyncSession, org: uuid.UUID, case_id: uuid.UUID
) -> list[EvidenceRequestOut]:
    await get_case(s, org, case_id)
    rows = await s.scalars(
        select(EvidenceRequest)
        .where(EvidenceRequest.organization_id == org, EvidenceRequest.case_id == case_id)
        .order_by(EvidenceRequest.created_at.desc())
    )
    return [EvidenceRequestOut.model_validate(r) for r in rows]


async def detail(
    s: AsyncSession, org: uuid.UUID, investigation_id: uuid.UUID
) -> InvestigationDetail:
    inv = await get_investigation(s, org, investigation_id)
    runs = await s.scalars(
        select(AgentRun)
        .where(AgentRun.organization_id == org, AgentRun.investigation_id == inv.id)
        .order_by(AgentRun.started_at)
    )
    requests = await s.scalars(
        select(EvidenceRequest)
        .where(EvidenceRequest.organization_id == org, EvidenceRequest.investigation_id == inv.id)
        .order_by(EvidenceRequest.created_at)
    )
    return InvestigationDetail.model_validate(inv).model_copy(
        update={
            "agent_runs": [AgentRunOut.model_validate(r) for r in runs],
            "evidence_requests": [EvidenceRequestOut.model_validate(r) for r in requests],
        }
    )


async def events_after(
    s: AsyncSession, org: uuid.UUID, investigation_id: uuid.UUID, after_seq: int
) -> list[AgentEventOut]:
    rows = await s.scalars(
        select(AgentEvent)
        .where(
            AgentEvent.organization_id == org,
            AgentEvent.investigation_id == investigation_id,
            AgentEvent.seq > after_seq,
        )
        .order_by(AgentEvent.seq)
        .limit(200)
    )
    return [AgentEventOut.model_validate(r) for r in rows]


async def approve(
    s: AsyncSession, principal: Principal, investigation_id: uuid.UUID, meta: RequestMeta
) -> InvestigationOut:
    org = principal.organization_id
    inv = await get_investigation(s, org, investigation_id, lock=True)
    if inv.status != InvestigationStatus.AWAITING_REVIEW:
        raise ConflictError(
            f"Only an investigation awaiting review can be approved ({inv.status})."
        )
    inv.status = InvestigationStatus.APPROVED
    inv.approved_by = principal.user_id
    inv.approved_at = datetime.now(UTC)
    await s.flush()
    await _event(s, inv, "approved", {"by": str(principal.user_id)})
    await audit.record(
        s,
        "investigation.approve",
        organization_id=org,
        actor_user_id=principal.user_id,
        resource_type="investigation",
        resource_id=inv.id,
        meta=meta,
    )
    return InvestigationOut.model_validate(inv)


async def request_evidence(
    s: AsyncSession,
    principal: Principal,
    investigation_id: uuid.UUID,
    document_types: list[str],
    note: str,
    meta: RequestMeta,
) -> EvidenceRequestOut:
    org = principal.organization_id
    inv = await get_investigation(s, org, investigation_id, lock=True)
    types = sorted({t.strip()[:60] for t in document_types if t.strip()})
    if not types:
        raise ConflictError("Name at least one document type.")
    req = EvidenceRequest(
        id=uuid.uuid4(),
        organization_id=org,
        case_id=inv.case_id,
        investigation_id=inv.id,
        document_types=types,
        note=note.strip(),
        created_by=principal.user_id,
    )
    s.add(req)
    await s.flush()
    await _event(s, inv, "evidence_requested", {"document_types": types})
    await audit.record(
        s,
        "investigation.request_evidence",
        organization_id=org,
        actor_user_id=principal.user_id,
        resource_type="investigation",
        resource_id=inv.id,
        meta=meta,
        metadata={"document_types": types},
    )
    await s.refresh(req)
    return EvidenceRequestOut.model_validate(req)
