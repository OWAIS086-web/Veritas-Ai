"""Investigation cases: create, list with document counts, update and soft delete."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationFailedError
from app.models import Case, Document, DocumentStatus, Finding, User
from app.schemas.common import Page, decode_cursor, encode_cursor
from app.schemas.documents import CaseCreate, CaseOut, CaseUpdate
from app.services.audit import service as audit
from app.services.identity.principal import Principal, RequestMeta


def _counts() -> Select[uuid.UUID, int, int, int]:
    return select(
        Document.case_id,
        func.count(Document.id),
        func.count(case((Document.status == DocumentStatus.COMPLETED, 1))),
        func.count(case((Document.status == DocumentStatus.FAILED, 1))),
    ).group_by(Document.case_id)


def _out(
    c: Case, email: str | None, counts: tuple[int, int, int] | None, findings: int = 0
) -> CaseOut:
    total, completed, failed = counts or (0, 0, 0)
    out = CaseOut.model_validate(c)
    return out.model_copy(
        update={
            "created_by_email": email,
            "document_count": total,
            "documents_completed": completed,
            "documents_failed": failed,
            "finding_count": findings if c.compared_at is not None else None,
        }
    )


async def _finding_counts(
    session: AsyncSession, org: uuid.UUID, case_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not case_ids:
        return {}
    rows = await session.execute(
        select(Finding.case_id, func.count())
        .where(
            Finding.organization_id == org,
            Finding.case_id.in_(case_ids),
            Finding.active.is_(True),
        )
        .group_by(Finding.case_id)
    )
    return {cid: int(n) for cid, n in rows.all()}


async def get_case(session: AsyncSession, org: uuid.UUID, case_id: uuid.UUID) -> Case:
    """A live (not deleted) case of this organization, else 404."""
    found = await session.scalar(
        select(Case).where(
            Case.id == case_id, Case.organization_id == org, Case.deleted_at.is_(None)
        )
    )
    if found is None:
        raise NotFoundError("Case not found.")
    return found


async def create(
    session: AsyncSession, principal: Principal, body: CaseCreate, meta: RequestMeta
) -> CaseOut:
    item = Case(
        id=uuid.uuid4(),
        organization_id=principal.organization_id,
        title=body.title.strip(),
        objective=body.objective.strip(),
        investigation_type=body.investigation_type,
        priority=body.priority,
        status="open",
        created_by=principal.user_id,
    )
    session.add(item)
    await session.flush()
    await session.refresh(item)
    await audit.record(
        session,
        "case.create",
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        resource_type="case",
        resource_id=item.id,
        meta=meta,
    )
    email = await session.scalar(select(User.email).where(User.id == principal.user_id))
    return _out(item, email, None)


async def list_cases(
    session: AsyncSession,
    org: uuid.UUID,
    *,
    limit: int,
    cursor: str | None,
    status: str | None,
    priority: str | None,
    q: str | None,
) -> Page[CaseOut]:
    stmt = (
        select(Case, User.email)
        .outerjoin(User, User.id == Case.created_by)
        .where(Case.organization_id == org, Case.deleted_at.is_(None))
    )
    if status:
        stmt = stmt.where(Case.status == status)
    if priority:
        stmt = stmt.where(Case.priority == priority)
    if q:
        pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(
            or_(Case.title.ilike(pattern, escape="\\"), Case.objective.ilike(pattern, escape="\\"))
        )
    if cursor:
        ts, cid = decode_cursor(cursor, 2)
        try:
            before, after_id = datetime.fromisoformat(ts), uuid.UUID(cid)
        except ValueError as exc:
            raise ValidationFailedError("Invalid pagination cursor.") from exc
        stmt = stmt.where(
            or_(Case.created_at < before, (Case.created_at == before) & (Case.id < after_id))
        )
    stmt = stmt.order_by(Case.created_at.desc(), Case.id.desc()).limit(limit + 1)
    rows = (await session.execute(stmt)).all()
    page_rows = rows[:limit]
    ids = [c.id for c, _ in page_rows]
    counts: dict[uuid.UUID, tuple[int, int, int]] = {}
    if ids:
        for case_id, total, completed, failed in (
            await session.execute(
                _counts().where(Document.case_id.in_(ids), Document.organization_id == org)
            )
        ).all():
            counts[case_id] = (total, completed, failed)
    found = await _finding_counts(session, org, ids)
    items = [_out(c, email, counts.get(c.id), found.get(c.id, 0)) for c, email in page_rows]
    next_cursor = None
    if len(rows) > limit and page_rows:
        last = page_rows[-1][0]
        next_cursor = encode_cursor(last.created_at, last.id)
    return Page[CaseOut](items=items, next_cursor=next_cursor)


async def get(session: AsyncSession, org: uuid.UUID, case_id: uuid.UUID) -> CaseOut:
    item = await get_case(session, org, case_id)
    email = await session.scalar(select(User.email).where(User.id == item.created_by))
    row = (
        await session.execute(
            _counts().where(Document.case_id == case_id, Document.organization_id == org)
        )
    ).first()
    found = await _finding_counts(session, org, [case_id])
    return _out(item, email, (row[1], row[2], row[3]) if row else None, found.get(case_id, 0))


async def update(
    session: AsyncSession,
    principal: Principal,
    case_id: uuid.UUID,
    body: CaseUpdate,
    meta: RequestMeta,
) -> CaseOut:
    item = await get_case(session, principal.organization_id, case_id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in changes.items():
        setattr(item, key, value.strip() if isinstance(value, str) and key != "status" else value)
    await session.flush()
    await audit.record(
        session,
        "case.update",
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        resource_type="case",
        resource_id=case_id,
        meta=meta,
        metadata={"fields": sorted(changes)},
    )
    return await get(session, principal.organization_id, case_id)


async def soft_delete(
    session: AsyncSession, principal: Principal, case_id: uuid.UUID, meta: RequestMeta
) -> None:
    item = await get_case(session, principal.organization_id, case_id)
    item.deleted_at = datetime.now(UTC)
    await audit.record(
        session,
        "case.delete",
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        resource_type="case",
        resource_id=case_id,
        meta=meta,
    )
