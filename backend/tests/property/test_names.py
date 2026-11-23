"""Name normalization and similarity (entity_resolution.names)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from app.services.entity_resolution.names import name_similarity, normalize_name

names = st.text(max_size=40)


@given(names)
def test_normalization_is_idempotent(name: str) -> None:
    assert normalize_name(normalize_name(name)) == normalize_name(name)


@given(names, names)
def test_similarity_is_symmetric_and_bounded(a: str, b: str) -> None:
    score = name_similarity(a, b)
    assert 0.0 <= score <= 1.0
    assert score == name_similarity(b, a)


@given(names)
def test_a_name_is_identical_to_itself(name: str) -> None:
    assert name_similarity(name, name) == 1.0


@given(st.sampled_from(["Ltd", "Limited", "Inc.", "LLC", "Co.", "GmbH"]))
def test_legal_suffix_and_case_do_not_matter(suffix: str) -> None:
    assert name_similarity("Global Trading Ltd", f"GLOBAL TRADING {suffix}") == 1.0


def test_word_order_is_ignored() -> None:
    assert name_similarity("Trading Global Ltd", "Global Trading Limited") == 1.0


def test_different_companies_are_below_the_default_threshold() -> None:
    assert name_similarity("Global Trading Ltd", "Pacific Harbour Bank") < 0.85
    assert name_similarity("ABC Imports Inc.", "XYZ Exports Inc.") < 0.85
