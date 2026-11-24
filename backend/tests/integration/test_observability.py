# Req: observability-testing 2.1, 2.2, 2.3
"""Health with storage and worker liveness, admin metrics scoped to the organization, and
the models endpoint that never shows an API key."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import get_settings
from tests.integration.conftest import Account, login, register
from tests.integration.test_cases_and_upload import new_case, upload
from tests.integration.test_pipeline import run_job

pytestmark = pytest.mark.integration


async def test_health_reports_storage_and_worker_without_changing_status(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/api/v1/system/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert set(body["components"]) == {"database", "redis"}
    assert body["services"]["storage"]["status"] == "ok"
    worker = body["services"]["worker"]
    # The test broker has no worker; liveness is reported, and the API stays healthy.
    assert worker["status"] in ("ok", "error") and worker["detail"]
    assert "celery@" not in resp.text  # no worker host names on an unauthenticated endpoint


async def _member(client: httpx.AsyncClient, admin: Account, role: str) -> Account:
    person = await register(client, org_name=f"{role} home")
    added = await client.post(
        f"/api/v1/organizations/{admin.organization_id}/members",
        headers=admin.headers,
        json={"email": person.email, "role": role},
    )
    assert added.status_code == 201
    return await login(client, person, organization_id=admin.organization_id)


async def test_metrics_are_admin_only_and_count_only_this_organizations_stages(
    client: httpx.AsyncClient,
) -> None:
    admin = await register(client, org_name="Metrics Org")
    quiet = await register(client, org_name="Metrics Quiet Org")
    case = await new_case(client, admin, title="Metrics")
    body = await upload(client, admin, case["id"], [("rows.csv", b"amount,currency\n1,USD\n")])
    assert (await run_job(admin, body["job_id"])).value == "succeeded"

    resp = await client.get("/api/v1/system/metrics", headers=admin.headers)
    assert resp.status_code == 200, resp.text
    m = resp.json()
    stages = {s["stage"]: s for s in m["stages"]}
    assert {"parse", "classify", "extract", "validate"} <= set(stages)
    for name in ("parse", "classify", "extract", "validate"):
        assert stages[name]["succeeded"] == 1, stages[name]
    assert all(s["failed"] == 0 for s in stages.values())
    assert all(s["mean_seconds"] is None or s["mean_seconds"] >= 0 for s in stages.values())
    assert [q["queue"] for q in m["queues"]] == ["celery"]
    assert m["queues"][0]["waiting"] is None or m["queues"][0]["waiting"] >= 0

    other = (await client.get("/api/v1/system/metrics", headers=quiet.headers)).json()
    assert other["stages"] == []  # another organization's documents never count here

    for role in ("investigation_manager", "investigator", "reviewer", "read_only_analyst"):
        member = await _member(client, admin, role)
        denied = await client.get("/api/v1/system/metrics", headers=member.headers)
        assert denied.status_code == 403, role


async def test_models_lists_configuration_and_reachability_but_never_the_key(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    acct = await register(client, org_name="Models Org")
    s = get_settings()
    monkeypatch.setattr(s, "llm_base_url", "")
    unconfigured = (await client.get("/api/v1/system/models", headers=acct.headers)).json()
    # Without an endpoint, model names may still be set; nothing is reachable or checked.
    assert unconfigured["configured"] is False and unconfigured["reachable"] is False
    assert all(m["available"] is None for m in unconfigured["models"])
    assert unconfigured["embeddings"] == "not_built"

    secret = "sk-test-" + "z" * 24
    monkeypatch.setattr(s, "llm_base_url", "http://127.0.0.1:9/v1")  # nothing listens on 9
    monkeypatch.setattr(s, "llm_api_key", secret)
    monkeypatch.setattr(s, "llm_model", "qwen2.5:7b-instruct")
    monkeypatch.setattr(s, "vlm_model", "qwen2.5vl:7b")
    monkeypatch.setattr(s, "llm_fallback_models", "backup-model")
    resp = await client.get("/api/v1/system/models", headers=acct.headers)
    assert resp.status_code == 200
    assert secret not in resp.text and "127.0.0.1:9/v1" not in resp.text
    body = resp.json()
    assert body["configured"] is True and body["api_key_set"] is True
    assert body["endpoint_host"] == "127.0.0.1"
    assert body["reachable"] is False and "not reachable" in body["error"]
    assert [(m["role"], m["model"], m["available"]) for m in body["models"]] == [
        ("text", "qwen2.5:7b-instruct", None),
        ("vision", "qwen2.5vl:7b", None),
        ("fallback", "backup-model", None),
    ]
    assert (await client.get("/api/v1/system/models")).status_code == 401
