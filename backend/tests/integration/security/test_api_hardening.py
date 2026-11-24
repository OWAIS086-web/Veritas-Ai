# Req: enterprise-security 3.2, 3.3
"""CORS is limited to the configured origins, and upload and investigation starts are rate
limited per member (429 with Retry-After), like login."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import get_settings
from tests.integration.conftest import register
from tests.integration.test_cases_and_upload import new_case

pytestmark = pytest.mark.integration
ALLOWED = "http://localhost:8080"


async def test_cors_answers_only_configured_origins(client: httpx.AsyncClient) -> None:
    assert ALLOWED in get_settings().cors_origin_list
    good = await client.options(
        "/api/v1/cases",
        headers={"Origin": ALLOWED, "Access-Control-Request-Method": "GET"},
    )
    assert good.headers.get("access-control-allow-origin") == ALLOWED
    assert "access-control-allow-credentials" not in good.headers
    for origin in ("https://evil.example", "http://localhost:8080.evil.example", "null"):
        bad = await client.options(
            "/api/v1/cases",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )
        assert "access-control-allow-origin" not in bad.headers, origin
        simple = await client.get("/api/v1/system/health", headers={"Origin": origin})
        assert "access-control-allow-origin" not in simple.headers, origin
    # Methods outside the API's own set are not offered to any origin.
    put = await client.options(
        "/api/v1/cases", headers={"Origin": ALLOWED, "Access-Control-Request-Method": "PUT"}
    )
    assert put.status_code == 400


async def test_uploads_are_rate_limited_per_member(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "upload_rate_limit_per_minute", 2)
    acct = await register(client, org_name="Rate Limit Org")
    other = await register(client, org_name="Rate Limit Other")
    case = await new_case(client, acct, title="Uploads")
    files = [("files", ("a.csv", b"amount,currency\n1,USD\n", "text/csv"))]
    url = f"/api/v1/cases/{case['id']}/documents"
    for _ in range(2):
        assert (await client.post(url, headers=acct.headers, files=files)).status_code == 201
    limited = await client.post(url, headers=acct.headers, files=files)
    assert limited.status_code == 429
    assert limited.headers["content-type"].startswith("application/problem+json")
    assert 1 <= int(limited.headers["retry-after"]) <= 60
    # The comparison-lab upload shares the same budget.
    pair = await client.post(
        f"/api/v1/cases/{case['id']}/comparisons/upload",
        headers=acct.headers,
        files={
            "original": ("a.pdf", b"%PDF-1.7", "application/pdf"),
            "test": ("b.pdf", b"%PDF-1.7 x", "application/pdf"),
        },
    )
    assert pair.status_code == 429
    # Another member's budget is separate (and their case is theirs).
    other_case = await new_case(client, other, title="Other uploads")
    ok = await client.post(
        f"/api/v1/cases/{other_case['id']}/documents", headers=other.headers, files=files
    )
    assert ok.status_code == 201


async def test_rate_limit_counts_only_permitted_requests(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A request refused for authentication never reaches (or uses up) the limiter."""
    monkeypatch.setattr(get_settings(), "upload_rate_limit_per_minute", 1)
    acct = await register(client, org_name="Rate Limit Anon")
    case = await new_case(client, acct, title="Anon")
    url = f"/api/v1/cases/{case['id']}/documents"
    files = [("files", ("a.csv", b"amount,currency\n1,USD\n", "text/csv"))]
    for _ in range(3):
        assert (await client.post(url, files=files)).status_code == 401
    assert (await client.post(url, headers=acct.headers, files=files)).status_code == 201


async def test_investigation_starts_are_rate_limited(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "investigation_rate_limit_per_minute", 1)
    acct = await register(client, org_name="Investigation Limit Org")
    case = await new_case(client, acct, title="Investigation limit")
    url = f"/api/v1/cases/{case['id']}/investigate"
    first = await client.post(url, headers=acct.headers, json={"objective": "Check"})
    assert first.status_code in (202, 409, 422), first.text  # not limited
    second = await client.post(url, headers=acct.headers, json={"objective": "Check"})
    assert second.status_code == 429
    assert "investigation" in second.json()["detail"]
