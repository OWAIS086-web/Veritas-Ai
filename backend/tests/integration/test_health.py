# Req: platform-foundation 2.1, 2.3, 3.1
from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.integration


async def test_health_ok(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/system/health")
    assert resp.status_code == 200
    body = resp.json()
    graph = body.pop("graph")
    # Since phase 9: storage and worker liveness, reported without changing the status.
    services = body.pop("services")
    assert set(services) == {"storage", "worker"}
    assert services["storage"] == {"status": "ok", "detail": None}
    assert services["worker"]["status"] in ("ok", "error") and services["worker"]["detail"]
    assert body == {
        "status": "ok",
        "components": {
            "database": {"status": "ok", "detail": None},
            "redis": {"status": "ok", "detail": None},
        },
    }
    # Since phase 4: the optional graph sync, reported without changing the overall status.
    # Other tests in this database leave a dead row on purpose, so counts are not fixed here.
    assert graph["status"] == "ok" and graph["detail"] is None
    assert set(graph) == {"status", "detail", "outbox_pending", "outbox_dead"}


async def test_request_id_echoed_and_generated(client: httpx.AsyncClient) -> None:
    given = await client.get("/api/v1/system/health", headers={"X-Request-ID": "abc-123"})
    assert given.headers["X-Request-ID"] == "abc-123"
    unsafe = await client.get("/api/v1/system/health", headers={"X-Request-ID": "bad id\n"})
    assert unsafe.headers["X-Request-ID"] != "bad id\n"
    assert len(unsafe.headers["X-Request-ID"]) == 32


async def test_unknown_route_is_problem_json(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert set(resp.json()) >= {"type", "title", "status", "detail", "instance"}


async def test_openapi_served(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/openapi.json")
    assert resp.status_code == 200
    assert "/api/v1/auth/login" in resp.json()["paths"]
