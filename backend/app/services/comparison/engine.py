"""Run every registered rule over the fields of one case. Pure: no database access.

A rule that raises is isolated: its id is reported as failed and the other rules still run.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.services.comparison.model import DocInfo, FieldObs, FindingDraft, RuleContext, RuleSpec
from app.services.comparison.rules import ALL_RULES

logger = get_logger(__name__)


@dataclass
class EngineResult:
    drafts: list[FindingDraft] = field(default_factory=list)
    ran: list[str] = field(default_factory=list)  # rule_id@version
    failed: dict[str, str] = field(default_factory=dict)  # rule_id -> error type


def evaluate_all(
    fields: Sequence[FieldObs],
    docs: Sequence[DocInfo],
    ctx: RuleContext,
    rules: Sequence[RuleSpec] = ALL_RULES,
) -> EngineResult:
    result = EngineResult()
    keys: set[str] = set()
    for rule in rules:
        try:
            drafts = rule.evaluate(fields, docs, ctx)
            new_keys = [d.key for d in drafts]
            if len(set(new_keys)) != len(new_keys) or keys & set(new_keys):
                raise ValueError("duplicate finding key")
        except Exception as exc:
            logger.warning("comparison_rule_failed", extra={"rule": rule.rule_id})
            result.failed[rule.rule_id] = type(exc).__name__
            continue
        result.ran.append(f"{rule.rule_id}@{rule.version}")
        keys.update(new_keys)
        result.drafts.extend(drafts)
    return result
