# Req: authentication-rbac 6.3; platform-foundation 2.4, 3.1, 3.2
from __future__ import annotations

import itertools
import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.errors import ConflictError, NotFoundError, register_error_handlers
from app.core.logging import JsonFormatter
from app.core.permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS, Role, has_permission

WRITE_PERMISSIONS = {
    "org:update",
    "members:manage",
    "cases:write",
    "cases:delete",
    "documents:upload",
    "documents:process",
    "findings:review",
    "findings:run",
    "findings:comment",
    "graph:rebuild",
    "system:ping",
}


def test_every_role_is_mapped_to_known_permissions() -> None:
    assert set(ROLE_PERMISSIONS) == set(Role)
    for perms in ROLE_PERMISSIONS.values():
        assert perms <= ALL_PERMISSIONS


def test_admin_has_everything_and_read_only_cannot_write() -> None:
    assert ROLE_PERMISSIONS[Role.ORG_ADMIN] == ALL_PERMISSIONS
    assert not (ROLE_PERMISSIONS[Role.READ_ONLY_ANALYST] & WRITE_PERMISSIONS)
    assert not (ROLE_PERMISSIONS[Role.REVIEWER] & {"documents:upload", "cases:write"})
    assert has_permission("reviewer", "findings:review")
    assert not has_permission("reviewer", "findings:run")
    # Investigators run comparisons and comment, but only reviewers decide on findings.
    assert has_permission("investigator", "findings:run")
    assert not has_permission("investigator", "findings:review")
    assert all(has_permission(r.value, "findings:read") for r in Role)
    assert not has_permission("not-a-role", "org:read")


def test_role_hierarchy_is_monotonic() -> None:
    order = [Role.READ_ONLY_ANALYST, Role.INVESTIGATOR, Role.INVESTIGATION_MANAGER, Role.ORG_ADMIN]
    for lower, higher in itertools.pairwise(order):
        assert ROLE_PERMISSIONS[lower] <= ROLE_PERMISSIONS[higher]


class Body(BaseModel):
    n: int


def _app() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/missing")
    async def missing() -> None:
        raise NotFoundError("Thing not found.")

    @app.get("/conflict")
    async def conflict() -> None:
        raise ConflictError()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.post("/validate")
    async def validate(body: Body) -> int:
        return body.n

    return TestClient(app, raise_server_exceptions=False)


def test_domain_errors_render_problem_json() -> None:
    client = _app()
    r = client.get("/missing")
    assert r.status_code == 404
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json() == {
        "type": "about:blank",
        "title": "Not found",
        "status": 404,
        "detail": "Thing not found.",
        "instance": "/missing",
    }
    assert client.get("/conflict").status_code == 409


def test_validation_errors_list_fields() -> None:
    r = _app().post("/validate", json={"n": "x"})
    assert r.status_code == 422
    assert r.json()["errors"][0]["loc"] == ["body", "n"]


def test_unhandled_errors_hide_internals() -> None:
    r = _app().get("/boom")
    assert r.status_code == 500
    assert "secret internal detail" not in r.text
    assert "Traceback" not in r.text


def test_log_formatter_redacts_sensitive_fields() -> None:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "evt", None, None)
    record.password = "hunter2-hunter2"  # type: ignore[attr-defined]
    record.refresh_token = "abc"  # type: ignore[attr-defined]
    record.path = "/x"  # type: ignore[attr-defined]
    line = json.loads(JsonFormatter().format(record))
    assert line["password"] == "[redacted]" and line["refresh_token"] == "[redacted]"
    assert line["path"] == "/x" and line["event"] == "evt"
