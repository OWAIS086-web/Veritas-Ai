"""Merging model claims with the rules extractor (extraction.merge)."""

from __future__ import annotations

from dataclasses import replace

from hypothesis import given
from hypothesis import strategies as st

from app.services.extraction.merge import merge_llm_with_rules
from app.services.extraction.result import EXTRACTED, UNCERTAIN, ExtractedValue


def _value(
    name: str, method: str, status: str = EXTRACTED, reason: str | None = None
) -> ExtractedValue:
    return ExtractedValue(
        name=name,
        value_type="amount",
        value="USD 68,000.00" if status == EXTRACTED else "68000.00",
        normalized={"amount": "68000.00", "currency": "USD"} if status == EXTRACTED else None,
        currency="USD",
        semantic_role=None,
        confidence=1.0 if status == EXTRACTED else None,
        page_number=1,
        bbox=(1.0, 2.0, 3.0, 4.0) if status == EXTRACTED else None,
        location=None,
        method=method,
        model_version=method,
        status=status,
        rejection_reason=reason,
    )


def test_a_rejected_claim_is_replaced_by_the_verified_rules_value_and_recorded() -> None:
    llm = [
        _value("document_number", "llm"),
        _value("total_amount", "llm", UNCERTAIN, "value_not_on_cited_page"),
    ]
    rules = [_value("document_number", "text_layer"), _value("total_amount", "text_layer")]
    values, notes = merge_llm_with_rules(llm, rules)
    assert [(v.name, v.method) for v in values] == [
        ("document_number", "llm"),
        ("total_amount", "text_layer"),
    ]
    assert notes == {
        "llm_rejected": {"total_amount": "value_not_on_cited_page"},
        "replaced_by_rules": ["total_amount"],
    }
    # Notes name fields and reasons only; the claimed value is document content.
    assert "68000.00" not in repr(notes)


def test_without_a_verified_stand_in_the_field_stays_uncertain() -> None:
    llm = [_value("buyer", "llm", UNCERTAIN, "model_returned_null")]
    rules = [_value("buyer", "text_layer", UNCERTAIN, "not_found")]
    values, notes = merge_llm_with_rules(llm, rules)
    assert values == llm
    assert notes == {"llm_rejected": {"buyer": "model_returned_null"}, "replaced_by_rules": []}


names = st.lists(st.sampled_from(["a", "b", "c", "d", "e"]), unique=True, max_size=5)


@given(
    names,
    st.lists(st.booleans(), min_size=5, max_size=5),
    st.lists(st.booleans(), min_size=5, max_size=5),
)
def test_verified_claims_are_never_replaced_and_fields_are_preserved(
    fields: list[str], llm_ok: list[bool], rules_ok: list[bool]
) -> None:
    llm = [
        _value(n, "llm", EXTRACTED if llm_ok[i] else UNCERTAIN, None if llm_ok[i] else "x")
        for i, n in enumerate(fields)
    ]
    rules = [
        replace(_value(n, "text_layer", EXTRACTED if rules_ok[i] else UNCERTAIN))
        for i, n in enumerate(fields)
    ]
    values, notes = merge_llm_with_rules(llm, rules)
    assert [v.name for v in values] == fields
    for i, v in enumerate(values):
        if llm_ok[i]:
            assert v.method == "llm"
        else:
            assert v.method == ("text_layer" if rules_ok[i] else "llm")
    assert set(notes["replaced_by_rules"]) <= set(notes["llm_rejected"])
