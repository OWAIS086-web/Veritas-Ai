"""Duplicate documents: identical bytes, or the same document number on different files."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from app.services.comparison.model import (
    DocInfo,
    EvidenceDraft,
    FieldObs,
    FindingDraft,
    RuleContext,
    RuleSpec,
    cite,
    doc_label,
)

RULE_ID = "duplicates.documents"
VERSION = "1.0"


def evaluate(
    fields: Sequence[FieldObs], docs: Sequence[DocInfo], ctx: RuleContext
) -> list[FindingDraft]:
    numbers = {f.document_id: f for f in fields if f.name == "document_number" and f.usable}
    drafts: list[FindingDraft] = []

    # Identical bytes. Upload already rejects these within one case; the rule still checks,
    # so documents added another way (versions, imports) are covered.
    by_hash: dict[str, list[DocInfo]] = defaultdict(list)
    for d in docs:
        by_hash[d.sha256].append(d)
    for sha, same in sorted(by_hash.items()):
        if len(same) < 2:
            continue
        names = ", ".join(sorted(d.filename for d in same))
        drafts.append(
            FindingDraft(
                rule_id=RULE_ID,
                rule_version=VERSION,
                signature=f"sha256:{sha}",
                type="duplicate_document",
                title="The same file appears more than once",
                severity="low",
                severity_rationale="Low: identical files add no new information.",
                explanation=f"These files have the same SHA-256 ({sha[:12]}…): {names}.",
                recommended_action="Keep one copy and confirm why the file was submitted twice.",
                evidence=[
                    EvidenceDraft(numbers[d.id], "supporting") for d in same if d.id in numbers
                ],
                details={"sha256": sha, "documents": sorted(str(d.id) for d in same)},
            )
        )

    # The same document number on files with different content.
    by_number: dict[tuple[str, str], list[FieldObs]] = defaultdict(list)
    hashes = {d.id: d.sha256 for d in docs}
    for f in numbers.values():
        key = str(f.normalized.get("key") or "")
        if key and f.doc_type:
            by_number[(f.doc_type, key)].append(f)
    for (doc_type, key), same_number in sorted(by_number.items()):
        if len({hashes.get(f.document_id) for f in same_number}) < 2:
            continue
        ordered = sorted(same_number, key=lambda f: f.filename)
        drafts.append(
            FindingDraft(
                rule_id=RULE_ID,
                rule_version=VERSION,
                signature=f"number:{doc_type}:{key}",
                type="duplicate_document",
                title=f"Two different files carry the same {doc_label(doc_type).lower()} number",
                severity="medium",
                severity_rationale=(
                    "Medium: different content under one document number can mean an amended "
                    "or a second version of the document."
                ),
                explanation="; ".join(f'{cite(f)} has number "{f.value}"' for f in ordered)
                + ". The files' contents differ.",
                recommended_action=(
                    "Compare the files side by side and confirm which version is the one that "
                    "was relied on."
                ),
                evidence=[EvidenceDraft(f, "supporting") for f in ordered],
                field="document_number",
                limitations=["Amended or reissued documents legitimately reuse a number."],
            )
        )
    return drafts


RULES = (RuleSpec(RULE_ID, VERSION, evaluate),)
