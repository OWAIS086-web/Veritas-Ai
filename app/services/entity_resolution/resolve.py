"""Turn extracted fields into case entities. Pure and deterministic: no database access.

Organizations (supplier, buyer, insurer fields) are grouped by normalized name. Groups are
compared only within a blocking key (the first token of the normalized name). Pairs at or
above the merge threshold become one entity; pairs between the flag threshold and the merge
threshold stay separate and are both marked `possible_duplicate`. Shipments and
transactions are grouped by their normalized reference only (no fuzzy matching).
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import combinations

from app.services.comparison.model import FieldObs
from app.services.entity_resolution.names import name_similarity, normalize_name

NAMESPACE = uuid.UUID("6c1f3a52-5d0e-4c4e-9a43-0f6b8d6c2a11")
ENTITY_FIELDS: dict[str, str] = {
    "supplier": "organization",
    "buyer": "organization",
    "insurer": "organization",
    "bank": "organization",
    "shipment_reference": "shipment",
    "bank_reference": "transaction",
    "supplier_address": "address",
    "buyer_address": "address",
    "goods": "product",
}


@dataclass
class ResolvedEntity:
    id: uuid.UUID
    type: str
    canonical_name: str
    normalized_name: str
    mentions: list[FieldObs]
    similarity: float  # lowest similarity inside the entity (1.0 for exact matches)
    confidence: Decimal | None
    status: str  # resolved | possible_duplicate
    possible_duplicates: list[str] = field(default_factory=list)  # normalized names


def entity_id(case_id: uuid.UUID, type_: str, normalized: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{case_id}:{type_}:{normalized}")


def _key(obs: FieldObs, type_: str) -> str:
    norm = obs.normalized if isinstance(obs.normalized, dict) else {}
    if type_ == "organization":
        return str(norm.get("key") or normalize_name(str(norm.get("name") or obs.value or "")))
    return str(norm.get("key") or "")


def _raw(obs: FieldObs) -> str:
    norm = obs.normalized if isinstance(obs.normalized, dict) else {}
    raw = norm.get("name") or norm.get("reference") or norm.get("text") or obs.value or ""
    return str(raw).strip()


def _confidence(similarity: float, mentions: Sequence[FieldObs]) -> Decimal | None:
    values = [m.confidence for m in mentions]
    if any(v is None for v in values):
        return None
    lowest = min([Decimal(str(round(similarity, 3))), *(v for v in values if v is not None)])
    return lowest.quantize(Decimal("0.001"))


class _UnionFind:
    def __init__(self, items: Sequence[str]) -> None:
        self.parent = {i: i for i in items}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Deterministic root: the smaller key wins.
            lo, hi = sorted((ra, rb))
            self.parent[hi] = lo


def resolve(
    case_id: uuid.UUID,
    fields: Sequence[FieldObs],
    merge_threshold: float,
    flag_threshold: float,
) -> list[ResolvedEntity]:
    groups: dict[tuple[str, str], list[FieldObs]] = defaultdict(list)
    for f in fields:
        type_ = ENTITY_FIELDS.get(f.name)
        if type_ is None or not f.usable:
            continue
        key = _key(f, type_)
        if key:
            groups[(type_, key)].append(f)

    entities: list[ResolvedEntity] = []
    for type_ in sorted({t for t, _ in groups}):
        keys = sorted(k for t, k in groups if t == type_)
        uf = _UnionFind(keys)
        pair_sim: dict[tuple[str, str], float] = {}
        flagged: dict[str, set[str]] = defaultdict(set)
        if type_ == "organization":
            blocks: dict[str, list[str]] = defaultdict(list)
            for k in keys:
                blocks[k.split(" ", 1)[0]].append(k)
            for block in blocks.values():
                for a, b in combinations(sorted(block), 2):
                    sim = name_similarity(a, b)
                    pair_sim[(a, b)] = sim
                    if sim >= merge_threshold:
                        uf.union(a, b)
                    elif sim >= flag_threshold:
                        flagged[a].add(b)
                        flagged[b].add(a)
        clusters: dict[str, list[str]] = defaultdict(list)
        for k in keys:
            clusters[uf.find(k)].append(k)
        for members in clusters.values():
            mentions = sorted(
                (m for k in members for m in groups[(type_, k)]),
                key=lambda m: (m.filename, m.name, str(m.field_id)),
            )
            sims = [pair_sim.get((a, b), 1.0) for a, b in combinations(sorted(members), 2)]
            similarity = min(sims, default=1.0)
            # The most mentioned key names the entity; ties go to the smallest key.
            sizes = Counter({k: len(groups[(type_, k)]) for k in members})
            normalized = min(members, key=lambda k: (-sizes[k], k))
            raws = Counter(_raw(m) for m in mentions if _key(m, type_) == normalized)
            canonical = min(raws, key=lambda r: (-raws[r], r)) if raws else normalized
            others = sorted({o for k in members for o in flagged[k]} - set(members))
            entities.append(
                ResolvedEntity(
                    id=entity_id(case_id, type_, normalized),
                    type=type_,
                    canonical_name=canonical[:300],
                    normalized_name=normalized[:300],
                    mentions=mentions,
                    similarity=similarity,
                    confidence=_confidence(similarity, mentions),
                    status="possible_duplicate" if others else "resolved",
                    possible_duplicates=others,
                )
            )
    entities.sort(key=lambda e: (e.type, e.normalized_name))
    return entities
