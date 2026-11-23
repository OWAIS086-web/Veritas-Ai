"""Document forensics results."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, require_permission
from app.schemas.common import PROBLEM_RESPONSES
from app.schemas.forensics import ForensicRunOut, ForensicSummaryOut
from app.services.forensics import queries
from app.services.identity.principal import Principal

router = APIRouter(tags=["forensics"], responses=PROBLEM_RESPONSES)


@router.get(
    "/documents/{document_id}/forensics",
    response_model=ForensicRunOut | None,
    summary="Latest forensic run of a document, with its anomalies and limitations",
)
async def document_forensics(
    document_id: uuid.UUID,
    principal: Principal = Depends(require_permission("forensics:read")),
    session: AsyncSession = Depends(db_session),
) -> ForensicRunOut | None:
    return await queries.latest_run(session, principal.organization_id, document_id)


@router.get(
    "/cases/{case_id}/forensics",
    response_model=list[ForensicSummaryOut],
    summary="Forensic summary of every document of a case, documents to review first",
)
async def case_forensics(
    case_id: uuid.UUID,
    principal: Principal = Depends(require_permission("forensics:read")),
    session: AsyncSession = Depends(db_session),
) -> list[ForensicSummaryOut]:
    return await queries.case_summary(session, principal.organization_id, case_id)
