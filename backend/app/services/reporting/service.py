"""Reports: request, list, read, signed download, and the worker-side generation.

Generation runs build → verify → render → store. A report that fails verification is
`failed` with the bad references and no stored file. Every query filters `organization_id`
(RLS is the backstop); another organization's report is a 404.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import tenant_session
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.logging import get_logger
from app.core.signing import REPORT_ARTIFACT, sign
from app.integrations.storage.base import ObjectStore, derived_key
from app.models import Case, Investigation, InvestigationStatus, Report, User
from app.schemas.reporting import DownloadOut, ReportDetail, ReportOut
from app.services.audit import service as audit
from app.services.cases.service import get_case
from app.services.identity.principal import Principal, RequestMeta
from app.services.reporting.builder import build_report
from app.services.reporting.model import NOT_REVIEWED
from app.services.reporting.render import MIME, render
from app.services.reporting.verify import ReportVerificationError, verify_report

logger = get_logger(__name__)
_SAFE = re.compile(r"[^A-Za-z0-9-]+")


def _out(r: Report, email: str | None) -> ReportOut:
    discrepancies = (r.model_json or {}).get("identified_discrepancies", [])
    return ReportOut.model_validate(r).model_copy(
        update={
            "created_by_email": email,
            "findings_total": len(discrepancies),
            "findings_not_reviewed": sum(
                1 for d in discrepancies if d.get("review_label") == NOT_REVIEWED
            ),
        }
    )


async def get_report(s: AsyncSession, org: uuid.UUID, report_id: uuid.UUID) -> Report:
    r = await s.scalar(
        select(Report)
        .join(Case, Case.id == Report.case_id)
        .where(Report.id == report_id, Report.organization_id == org, Case.deleted_at.is_(None))
    )
    if r is None:
        raise NotFoundError("Report not found.")
    return r


async def create(
    s: AsyncSession,
    principal: Principal,
    case_id: uuid.UUID,
    fmt: str,
    investigation_id: uuid.UUID | None,
    meta: RequestMeta,
) -> ReportOut:
    org = principal.organization_id
    await get_case(s, org, case_id)
    if investigation_id is not None:
        inv = await s.scalar(
            select(Investigation).where(
                Investigation.id == investigation_id,
                Investigation.organization_id == org,
                Investigation.case_id == case_id,
            )
        )
        if inv is None:
            raise NotFoundError("Investigation not found.")
        if inv.status != InvestigationStatus.COMPLETED or inv.approved_at is None:
            raise ConflictError(
                "A report can use an investigation only after it was approved and completed."
            )
    report = Report(
        id=uuid.uuid4(),
        organization_id=org,
        case_id=case_id,
        investigation_id=investigation_id,
        format=fmt,
        status="queued",
        model_json={},
        created_by=principal.user_id,
    )
    s.add(report)
    await s.flush()
    await audit.record(
        s,
        "report.request",
        organization_id=org,
        actor_user_id=principal.user_id,
        resource_type="report",
        resource_id=report.id,
        meta=meta,
        metadata={"case_id": str(case_id), "format": fmt},
    )
    await s.refresh(report)
    return _out(report, None)


async def list_for_case(s: AsyncSession, org: uuid.UUID, case_id: uuid.UUID) -> list[ReportOut]:
    await get_case(s, org, case_id)
    rows = await s.execute(
        select(Report, User.email)
        .outerjoin(User, User.id == Report.created_by)
        .where(Report.organization_id == org, Report.case_id == case_id)
        .order_by(Report.created_at.desc())
    )
    return [_out(r, email) for r, email in rows]


async def detail(s: AsyncSession, org: uuid.UUID, report_id: uuid.UUID) -> ReportDetail:
    r = await get_report(s, org, report_id)
    email = await s.scalar(select(User.email).where(User.id == r.created_by))
    return ReportDetail.model_validate(_out(r, email).model_dump()).model_copy(
        update={"model": r.model_json or None}
    )


async def download_link(
    s: AsyncSession, principal: Principal, report_id: uuid.UUID, meta: RequestMeta
) -> DownloadOut:
    org = principal.organization_id
    r = await get_report(s, org, report_id)
    if r.status != "completed":
        raise ConflictError(f"The report is {r.status}; there is no file to download.")
    token, expires = sign(r.id, org, get_settings().signed_url_seconds, artifact=REPORT_ARTIFACT)
    await audit.record(
        s,
        "report.access",
        organization_id=org,
        actor_user_id=principal.user_id,
        resource_type="report",
        resource_id=r.id,
        meta=meta,
        metadata={"purpose": "download_link"},
    )
    return DownloadOut(
        url=f"/api/v1/report-files/{token}", expires_at=datetime.fromtimestamp(expires, UTC)
    )


def file_name(case_title: str, r: Report) -> str:
    base = _SAFE.sub("-", case_title).strip("-")[:60] or "case"
    return f"veritas-report-{base}-{str(r.id)[:8]}.{r.format}"


async def generate(organization_id: uuid.UUID, report_id: uuid.UUID, store: ObjectStore) -> str:
    """Worker side. Idempotent: a finished report is left as it is."""
    async with tenant_session(organization_id) as s:
        r = await s.scalar(
            select(Report)
            .where(Report.id == report_id, Report.organization_id == organization_id)
            .with_for_update()
        )
        if r is None:
            return "missing"
        if r.status in ("completed", "failed"):
            return r.status
        r.status = "running"
    try:
        async with tenant_session(organization_id) as s:
            r = await get_report(s, organization_id, report_id)
            model = await build_report(
                s, organization_id, r.case_id, r.id, r.investigation_id, r.created_by
            )
            await verify_report(s, organization_id, r.case_id, model)
            fmt, created_by = r.format, r.created_by
        data = render(model, fmt)
        digest = hashlib.sha256(data).hexdigest()
        # A report file is a derived artifact (put_new is reserved for uploaded originals). The
        # key is fresh per attempt, so nothing is overwritten and an interrupted attempt can't
        # be mistaken for this file; the download re-checks the SHA-256 recorded below.
        key = derived_key(organization_id, report_id, f"report-{uuid.uuid4().hex[:12]}.{fmt}")
        await store.put_derived(key, data, MIME[fmt])
    except (ReportVerificationError, DomainError) as exc:
        problems = exc.problems if isinstance(exc, ReportVerificationError) else [str(exc)]
        await _fail(organization_id, report_id, problems)
        return "failed"
    except Exception as exc:
        logger.warning(
            "report_failed", extra={"report": str(report_id), "error": type(exc).__name__}
        )
        await _fail(organization_id, report_id, [f"internal error ({type(exc).__name__})"])
        return "failed"
    async with tenant_session(organization_id) as s:
        r = await get_report(s, organization_id, report_id)
        r.status = "completed"
        r.storage_key = key
        r.sha256 = digest
        r.size_bytes = len(data)
        r.model_json = model.model_dump(mode="json")
        r.finished_at = datetime.now(UTC)
        await audit.record(
            s,
            "report.generated",
            organization_id=organization_id,
            actor_user_id=created_by,
            resource_type="report",
            resource_id=report_id,
            metadata={"format": fmt, "sha256": digest, "summary": model.audit.summary_method},
        )
    return "completed"


async def _fail(organization_id: uuid.UUID, report_id: uuid.UUID, problems: list[str]) -> None:
    async with tenant_session(organization_id) as s:
        r = await get_report(s, organization_id, report_id)
        r.status = "failed"
        r.error = "; ".join(problems)[:4000]
        r.finished_at = datetime.now(UTC)
