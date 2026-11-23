"""Worker side of an investigation: start or resume the workflow, then record how it ended.

A redelivered task (worker crash) resumes from the last checkpoint. A paused investigation
(`awaiting_review`) is left alone until a human approves it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.agents.budget import Budget, BudgetExhausted
from app.agents.events import InvestigationContext
from app.agents.tools import ToolGateway
from app.core.db import tenant_session
from app.core.logging import get_logger
from app.core.permissions import permissions_for
from app.integrations.llm.base import LLMProvider
from app.integrations.llm.openai_compat import configured_provider
from app.models import (
    FINISHED_STATUSES,
    Investigation,
    InvestigationStatus,
    OrganizationMember,
    Role,
)
from app.workflows.investigation_pipeline import InvestigationFailed, Runtime, advance

logger = get_logger(__name__)
RUNNABLE = (InvestigationStatus.QUEUED, InvestigationStatus.RUNNING, InvestigationStatus.APPROVED)


async def _finish(
    ctx: InvestigationContext, status: str, error: str | None, event: str, data: dict[str, object]
) -> None:
    async with tenant_session(ctx.organization_id) as s:
        inv = await s.scalar(
            select(Investigation)
            .where(
                Investigation.id == ctx.investigation_id,
                Investigation.organization_id == ctx.organization_id,
            )
            .with_for_update()
        )
        if inv is None:
            return
        inv.status = status
        inv.error = error
        inv.usage = ctx.budget.usage()
        if status in FINISHED_STATUSES:
            inv.finished_at = datetime.now(UTC)
    await ctx.emit(event, data)


async def run_investigation(
    organization_id: uuid.UUID,
    investigation_id: uuid.UUID,
    provider: LLMProvider | None = None,
) -> str:
    """Advance one investigation. `provider` is injected only by tests (replay)."""
    async with tenant_session(organization_id) as s:
        inv = await s.scalar(
            select(Investigation)
            .where(
                Investigation.id == investigation_id,
                Investigation.organization_id == organization_id,
            )
            .with_for_update()
        )
        if inv is None or inv.status not in RUNNABLE:
            return inv.status if inv else "missing"
        resuming_report = inv.status == InvestigationStatus.APPROVED
        # The tools act with the starter's current role (re-read, as every request does).
        role = await s.scalar(
            select(Role.key)
            .join(OrganizationMember, OrganizationMember.role_id == Role.id)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == inv.created_by,
            )
        )
        if not resuming_report:
            inv.status = InvestigationStatus.RUNNING
            inv.started_at = inv.started_at or datetime.now(UTC)
        ctx = InvestigationContext(
            organization_id=organization_id,
            investigation_id=inv.id,
            case_id=inv.case_id,
            objective=inv.objective,
            budget=Budget.restore(inv.budget, inv.usage),
        )
    if role is None:
        # The tools act with the starter's permissions; a removed member can't run them.
        await _finish(
            ctx,
            InvestigationStatus.FAILED,
            "the user who started this investigation is no longer a member",
            "investigation_failed",
            {"reason": "starter_not_a_member"},
        )
        return InvestigationStatus.FAILED
    await ctx.emit("report_started" if resuming_report else "investigation_started", {})
    runtime = Runtime(
        ctx=ctx,
        gateway=ToolGateway(ctx, permissions_for(role)),
        provider=provider if provider is not None else configured_provider(),
    )
    try:
        outcome = await advance(runtime)
    except BudgetExhausted as exc:
        await _finish(
            ctx,
            InvestigationStatus.BUDGET_EXHAUSTED,
            str(exc),
            "budget_exhausted",
            {"limit": exc.limit, "used": exc.used, "maximum": exc.maximum},
        )
        return InvestigationStatus.BUDGET_EXHAUSTED
    except InvestigationFailed as exc:
        await _finish(
            ctx, InvestigationStatus.FAILED, str(exc), "investigation_failed", {"reason": str(exc)}
        )
        return InvestigationStatus.FAILED
    except Exception as exc:
        logger.warning(
            "investigation_failed",
            extra={"investigation": str(investigation_id), "error": type(exc).__name__},
        )
        await _finish(
            ctx,
            InvestigationStatus.FAILED,
            f"internal error ({type(exc).__name__})",
            "investigation_failed",
            {"reason": type(exc).__name__},
        )
        return InvestigationStatus.FAILED
    if outcome == InvestigationStatus.AWAITING_REVIEW:
        await _finish(ctx, outcome, None, "awaiting_review", {"usage": ctx.budget.usage()})
    else:
        await _finish(ctx, outcome, None, "investigation_completed", {"usage": ctx.budget.usage()})
    return outcome
