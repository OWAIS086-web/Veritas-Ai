"""Findings for the API. Every query filters organization_id explicitly (RLS is the backstop)
and hides findings of soft-deleted cases. Another organization's finding is a 404.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models import (
    Case,
    Document,
    EvidenceItem,
    EvidenceRequest,
    Finding,
    FindingDecision,
    FindingStatus,
    InvestigatorComment,
    OrganizationMember,
    User,
)
from app.schemas.common import Page, decode_cursor, encode_cursor
from app.schemas.findings import (
    CommentCreate,
    CommentOut,
    DecisionOut,
    EvidenceOut,
    FindingDetail,
    FindingSummary,
    StatusChange,
)
from app.schemas.investigations import EvidenceRequestCreate, EvidenceRequestOut
from app.services.audit import service as audit
from app.services.identity.principal import Principal, RequestMeta

NOTE_REQUIRED = {FindingStatus.DISMISSED, FindingStatus.CONFIRMED_OBSERVATION}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


def _visible(org: uuid.UUID) -> Select[Finding, str]:
    return (
        select(Finding, Case.title)
        .join(Case, Case.id == Finding.case_id)
        .where(Finding.organization_id == org, Case.deleted_at.is_(None))
    )


async def _evidence_counts(
    session: AsyncSession, org: uuid.UUID, ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    rows = await session.execute(
        select(EvidenceItem.finding_id, func.count())
        .where(EvidenceItem.organization_id == org, EvidenceItem.finding_id.in_(ids))
        .group_by(EvidenceItem.finding_id)
    )
    return {fid: int(n) for fid, n in rows.all()}


def _summary(f: Finding, case_title: str, evidence_count: int) -> FindingSummary:
    out = FindingSummary.model_validate(f)
    return out.model_copy(update={"case_title": case_title, "evidence_count": evidence_count})


async def list_findings(
    session: AsyncSession,
    org: uuid.UUID,
    *,
    case_id: uuid.UUID | None = None,
    status: str | None = None,
    severity: str | None = None,
    priority: str | None = None,
    finding_type: str | None = None,
    include_inactive: bool = False,
    limit: int = 50,
    cursor: str | None = None,
) -> Page[FindingSummary]:
    stmt = _visible(org)
    if case_id is not None:
        stmt = stmt.where(Finding.case_id == case_id)
    if status:
        stmt = stmt.where(Finding.status == status)
    if severity:
        stmt = stmt.where(Finding.severity == severity)
    if priority:
        stmt = stmt.where(Finding.priority == priority)
    if finding_type:
        stmt = stmt.where(Finding.type == finding_type)
    if not include_inactive:
        stmt = stmt.where(Finding.active.is_(True))
    if cursor:
        ts, fid = decode_cursor(cursor, 2)
        try:
            before, before_id = datetime.fromisoformat(ts), uuid.UUID(fid)
        except ValueError as exc:
            raise ValidationFailedError("Invalid pagination cursor.") from exc
        stmt = stmt.where(
            or_(
                Finding.created_at < before,
                (Finding.created_at == before) & (Finding.id < before_id),
            )
        )
    stmt = stmt.order_by(Finding.created_at.desc(), Finding.id.desc()).limit(limit + 1)
    rows = (await session.execute(stmt)).all()
    page = rows[:limit]
    counts = await _evidence_counts(session, org, [f.id for f, _ in page])
    items = [_summary(f, title, counts.get(f.id, 0)) for f, title in page]
    next_cursor = None
    if len(rows) > limit and page:
        last = page[-1][0]
        next_cursor = encode_cursor(last.created_at, last.id)
    return Page[FindingSummary](items=items, next_cursor=next_cursor)


async def list_for_case(
    session: AsyncSession, org: uuid.UUID, case_id: uuid.UUID, include_inactive: bool
) -> list[FindingSummary]:
    """Every finding of one case, most important first."""
    case = await session.scalar(
        select(Case.id).where(
            Case.id == case_id, Case.organization_id == org, Case.deleted_at.is_(None)
        )
    )
    if case is None:
        raise NotFoundError("Case not found.")
    stmt = _visible(org).where(Finding.case_id == case_id)
    if not include_inactive:
        stmt = stmt.where(Finding.active.is_(True))
    rows = (await session.execute(stmt)).all()
    counts = await _evidence_counts(session, org, [f.id for f, _ in rows])
    items = [_summary(f, title, counts.get(f.id, 0)) for f, title in rows]
    items.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.created_at, str(f.id)))
    return items


async def _get(session: AsyncSession, org: uuid.UUID, finding_id: uuid.UUID) -> tuple[Finding, str]:
    row = (await session.execute(_visible(org).where(Finding.id == finding_id))).first()
    if row is None:
        raise NotFoundError("Finding not found.")
    return row


async def evidence(
    session: AsyncSession, org: uuid.UUID, finding_id: uuid.UUID
) -> list[EvidenceOut]:
    await _get(session, org, finding_id)
    rows = (
        await session.execute(
            select(EvidenceItem, Document.original_filename, Document.doc_type)
            .join(Document, Document.id == EvidenceItem.document_id)
            .where(EvidenceItem.organization_id == org, EvidenceItem.finding_id == finding_id)
            .order_by(Document.original_filename, EvidenceItem.field_name, EvidenceItem.id)
        )
    ).all()
    return [
        EvidenceOut.model_validate(e).model_copy(
            update={"document_filename": name, "doc_type": doc_type}
        )
        for e, name, doc_type in rows
    ]


async def get(session: AsyncSession, org: uuid.UUID, finding_id: uuid.UUID) -> FindingDetail:
    finding, case_title = await _get(session, org, finding_id)
    items = await evidence(session, org, finding_id)
    decisions = [
        DecisionOut.model_validate(d).model_copy(update={"actor_email": email})
        for d, email in (
            await session.execute(
                select(FindingDecision, User.email)
                .outerjoin(User, User.id == FindingDecision.actor_user_id)
                .where(
                    FindingDecision.organization_id == org,
                    FindingDecision.finding_id == finding_id,
                )
                .order_by(FindingDecision.created_at, FindingDecision.id)
            )
        ).all()
    ]
    comments = [
        CommentOut.model_validate(c).model_copy(update={"user_email": email})
        for c, email in (
            await session.execute(
                select(InvestigatorComment, User.email)
                .outerjoin(User, User.id == InvestigatorComment.user_id)
                .where(
                    InvestigatorComment.organization_id == org,
                    InvestigatorComment.finding_id == finding_id,
                )
                .order_by(InvestigatorComment.created_at, InvestigatorComment.id)
            )
        ).all()
    ]
    summary = _summary(finding, case_title, len(items))
    return FindingDetail(
        **summary.model_dump(),
        explanation=finding.explanation,
        severity_rationale=finding.severity_rationale,
        limitations=finding.limitations,
        recommended_action=finding.recommended_action,
        coverage=finding.coverage,
        ai_output_json=finding.ai_output_json,
        evidence=items,
        decisions=decisions,
        comments=comments,
        assignee_email=await session.scalar(
            select(User.email).where(User.id == finding.assignee_user_id)
        )
        if finding.assignee_user_id
        else None,
        evidence_requests=[
            EvidenceRequestOut.model_validate(r)
            for r in await session.scalars(
                select(EvidenceRequest)
                .where(
                    EvidenceRequest.organization_id == org,
                    EvidenceRequest.finding_id == finding_id,
                )
                .order_by(EvidenceRequest.created_at)
            )
        ],
    )


async def assign(
    session: AsyncSession,
    principal: Principal,
    finding_id: uuid.UUID,
    user_id: uuid.UUID | None,
    meta: RequestMeta,
) -> FindingDetail:
    """Assign the finding to a member of the organization, or clear the assignment."""
    org = principal.organization_id
    finding, _ = await _get(session, org, finding_id)
    if user_id is not None:
        member = await session.scalar(
            select(OrganizationMember.id).where(
                OrganizationMember.organization_id == org, OrganizationMember.user_id == user_id
            )
        )
        if member is None:
            raise ValidationFailedError("The assignee must be a member of this organization.")
    previous = finding.assignee_user_id
    finding.assignee_user_id = user_id
    await session.flush()
    await audit.record(
        session,
        "finding.assign",
        organization_id=org,
        actor_user_id=principal.user_id,
        resource_type="finding",
        resource_id=finding_id,
        meta=meta,
        metadata={
            "from": str(previous) if previous else None,
            "to": str(user_id) if user_id else None,
        },
    )
    return await get(session, org, finding_id)


async def request_evidence(
    session: AsyncSession,
    principal: Principal,
    finding_id: uuid.UUID,
    body: EvidenceRequestCreate,
    meta: RequestMeta,
) -> EvidenceRequestOut:
    """Record a request for more documents for this finding; it is shown on the case."""
    org = principal.organization_id
    finding, _ = await _get(session, org, finding_id)
    types = sorted({t.strip()[:60] for t in body.document_types if t.strip()})
    if not types:
        raise ValidationFailedError("Name at least one document type.")
    req = EvidenceRequest(
        id=uuid.uuid4(),
        organization_id=org,
        case_id=finding.case_id,
        finding_id=finding_id,
        document_types=types,
        note=body.note.strip(),
        created_by=principal.user_id,
    )
    session.add(req)
    await session.flush()
    await session.refresh(req)
    await audit.record(
        session,
        "finding.request_evidence",
        organization_id=org,
        actor_user_id=principal.user_id,
        resource_type="finding",
        resource_id=finding_id,
        meta=meta,
        metadata={"document_types": types},
    )
    return EvidenceRequestOut.model_validate(req)


async def change_status(
    session: AsyncSession,
    principal: Principal,
    finding_id: uuid.UUID,
    body: StatusChange,
    meta: RequestMeta,
) -> FindingDetail:
    org = principal.organization_id
    finding, _ = await _get(session, org, finding_id)
    target = FindingStatus(body.status)
    note = (body.note or "").strip() or None
    if target == finding.status:
        raise ConflictError(f"The finding is already '{target.value}'.")
    if target in NOTE_REQUIRED and not note:
        raise ValidationFailedError(f"A note is required to set '{target.value}'.")
    if target == FindingStatus.CONFIRMED_OBSERVATION:
        count = (await _evidence_counts(session, org, [finding_id])).get(finding_id, 0)
        if count == 0:
            raise ConflictError(
                "A finding without evidence items can't be confirmed. Request the missing "
                "document or mark the finding as needing more evidence."
            )
    previous = finding.status
    finding.status = target.value
    try:
        # The database trigger enforces the evidence rule as well.
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("A finding without evidence items can't be confirmed.") from exc
    session.add(
        FindingDecision(
            organization_id=org,
            finding_id=finding_id,
            actor_user_id=principal.user_id,
            from_status=previous,
            to_status=target.value,
            note=note,
        )
    )
    await audit.record(
        session,
        "finding.review",
        organization_id=org,
        actor_user_id=principal.user_id,
        resource_type="finding",
        resource_id=finding_id,
        meta=meta,
        metadata={"from": previous, "to": target.value, "with_note": note is not None},
    )
    await session.flush()
    return await get(session, org, finding_id)


async def add_comment(
    session: AsyncSession,
    principal: Principal,
    finding_id: uuid.UUID,
    body: CommentCreate,
    meta: RequestMeta,
) -> CommentOut:
    org = principal.organization_id
    await _get(session, org, finding_id)
    text = body.body.strip()
    if not text:
        raise ValidationFailedError("A comment can't be empty.")
    comment = InvestigatorComment(
        id=uuid.uuid4(),
        organization_id=org,
        finding_id=finding_id,
        user_id=principal.user_id,
        body=text,
    )
    session.add(comment)
    await session.flush()
    await session.refresh(comment)
    await audit.record(
        session,
        "finding.comment",
        organization_id=org,
        actor_user_id=principal.user_id,
        resource_type="finding",
        resource_id=finding_id,
        meta=meta,
    )
    email = await session.scalar(select(User.email).where(User.id == principal.user_id))
    return CommentOut.model_validate(comment).model_copy(update={"user_email": email})


async def count_open(session: AsyncSession, org: uuid.UUID) -> tuple[int, int]:
    """(findings requiring review, high-priority findings) over active findings that are
    not yet decided."""
    undecided = (
        FindingStatus.NEW.value,
        FindingStatus.UNDER_REVIEW.value,
        FindingStatus.NEEDS_MORE_EVIDENCE.value,
    )
    base = (
        select(func.count())
        .select_from(Finding)
        .join(Case, Case.id == Finding.case_id)
        .where(
            Finding.organization_id == org,
            Finding.active.is_(True),
            Finding.status.in_(undecided),
            Case.deleted_at.is_(None),
        )
    )
    review = int(await session.scalar(base.where(Finding.requires_human_review.is_(True))) or 0)
    high = int(await session.scalar(base.where(Finding.priority == "high")) or 0)
    return review, high
