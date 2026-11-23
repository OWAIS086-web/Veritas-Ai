# Req: platform-foundation 5.2; authentication-rbac 1.4, 3.x
"""Hypothesis property tests for invariants that don't need infrastructure."""

from __future__ import annotations

import uuid

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.security import hash_password, hash_refresh_token, verify_password
from app.models import JobStatus
from app.services.identity.organizations import slugify
from app.services.identity.rate_limit import login_keys
from app.services.jobs.runner import backoff_seconds
from app.services.jobs.service import ALLOWED_TRANSITIONS, can_transition

statuses = st.sampled_from([s.value for s in JobStatus])


@settings(max_examples=12, deadline=None)  # argon2 is deliberately slow
@given(st.text(min_size=1, max_size=64), st.text(min_size=1, max_size=64))
def test_password_hash_verifies_only_the_original(pw: str, other: str) -> None:
    hashed = hash_password(pw)
    assert verify_password(pw, hashed)
    assert verify_password(other, hashed) == (other == pw)


@given(st.text(min_size=1, max_size=200))
def test_refresh_hash_is_deterministic_and_fixed_length(token: str) -> None:
    assert hash_refresh_token(token) == hash_refresh_token(token)
    assert len(hash_refresh_token(token)) == 64


@given(st.text(), st.text())
def test_refresh_hash_distinguishes_tokens(a: str, b: str) -> None:
    assert (hash_refresh_token(a) == hash_refresh_token(b)) == (a == b)


@given(st.lists(statuses, min_size=1, max_size=30))
def test_job_state_machine_never_leaves_a_terminal_state(walk: list[str]) -> None:
    current = JobStatus.QUEUED.value
    reached_terminal = False
    for proposed in walk:
        if can_transition(current, proposed):
            assert not reached_terminal, "a terminal job transitioned again"
            current = proposed
            reached_terminal = current in {"succeeded", "failed"}


@given(statuses)
def test_terminal_states_have_no_exits(status: str) -> None:
    for terminal in (JobStatus.SUCCEEDED, JobStatus.FAILED):
        assert not can_transition(terminal.value, status)
    assert ALLOWED_TRANSITIONS[JobStatus.SUCCEEDED] == frozenset()


@given(st.integers(min_value=0, max_value=50), st.integers(min_value=0, max_value=50))
def test_backoff_is_monotonic_and_capped(a: int, b: int) -> None:
    lo, hi = sorted((a, b))
    assert backoff_seconds(lo) <= backoff_seconds(hi) <= 60


@given(st.text(max_size=300))
def test_slug_is_url_safe_and_unique_suffixed(name: str) -> None:
    slug = slugify(name)
    assert len(slug) <= 80
    assert all(c.isascii() and (c.isalnum() or c == "-") for c in slug)
    assert slug != slugify(name)  # random suffix prevents collisions


@given(st.emails(), st.one_of(st.none(), st.ip_addresses().map(str)))
def test_rate_limit_keys_never_contain_the_raw_email(email: str, ip: str | None) -> None:
    keys = login_keys(ip, email)
    assert all(email not in k for k in keys)
    assert len(keys) == (2 if ip else 1)


@given(st.uuids(), st.uuids())
def test_uuid_strings_round_trip(a: uuid.UUID, b: uuid.UUID) -> None:
    # Tenant ids are bound to set_config as strings; the round trip must be lossless.
    assert uuid.UUID(str(a)) == a
    assert (str(a) == str(b)) == (a == b)
