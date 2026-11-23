# Req: authentication-rbac 6.3, 8.1
"""Role x endpoint permission matrix against the real API."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import httpx
import pytest

from app.core.permissions import ROLE_PERMISSIONS, Role
from tests.integration.conftest import Account, login, register

pytestmark = pytest.mark.integration

# (method, path template, permission, json body)
Endpoint = tuple[str, str, str, dict[str, object] | None]
ENDPOINTS: list[Endpoint] = [
    ("GET", "/api/v1/organizations/{org}", "org:read", None),
    ("PATCH", "/api/v1/organizations/{org}", "org:update", {"retention_days": 30}),
    ("GET", "/api/v1/organizations/{org}/members", "members:read", None),
    (
        "POST",
        "/api/v1/organizations/{org}/members",
        "members:manage",
        {"email": "missing-user@example.com", "role": "reviewer"},
    ),
    ("GET", "/api/v1/audit-logs", "audit:read", None),
    ("GET", "/api/v1/stats/overview", "stats:read", None),
    ("GET", "/api/v1/jobs/{random}", "jobs:read", None),
    ("GET", "/api/v1/findings", "findings:read", None),
    ("GET", "/api/v1/findings/{random}", "findings:read", None),
    ("GET", "/api/v1/findings/{random}/evidence", "findings:read", None),
    ("GET", "/api/v1/cases/{random}/findings", "findings:read", None),
    ("POST", "/api/v1/cases/{random}/compare", "findings:run", None),
    ("PATCH", "/api/v1/findings/{random}/status", "findings:review", {"status": "under_review"}),
    ("POST", "/api/v1/findings/{random}/comments", "findings:comment", {"body": "Checked."}),
    ("GET", "/api/v1/cases/{random}/graph", "graph:read", None),
    ("POST", "/api/v1/cases/{random}/graph/rebuild", "graph:rebuild", None),
    ("GET", "/api/v1/entities/{random}", "graph:read", None),
    ("GET", "/api/v1/entities/{random}/relationships", "graph:read", None),
    ("GET", "/api/v1/relationships/{random}/evidence", "graph:read", None),
    ("GET", "/api/v1/documents/{random}/forensics", "forensics:read", None),
    ("GET", "/api/v1/cases/{random}/forensics", "forensics:read", None),
    ("POST", "/api/v1/cases/{random}/reports", "reports:create", {"format": "pdf"}),
    ("GET", "/api/v1/cases/{random}/reports", "reports:read", None),
    ("GET", "/api/v1/reports/{random}", "reports:read", None),
    ("GET", "/api/v1/reports/{random}/download", "reports:read", None),
    ("PATCH", "/api/v1/findings/{random}/assignee", "findings:assign", {"user_id": None}),
    (
        "POST",
        "/api/v1/findings/{random}/evidence-requests",
        "findings:comment",
        {"document_types": ["freight_invoice"], "note": "Needed"},
    ),
    ("POST", "/api/v1/cases/{random}/investigate", "investigations:run", {"objective": "Check"}),
    ("GET", "/api/v1/cases/{random}/investigations", "investigations:read", None),
    ("GET", "/api/v1/cases/{random}/evidence-requests", "investigations:read", None),
    ("GET", "/api/v1/investigations/{random}", "investigations:read", None),
    ("GET", "/api/v1/investigations/{random}/events", "investigations:read", None),
    ("POST", "/api/v1/investigations/{random}/approve", "findings:review", None),
    (
        "POST",
        "/api/v1/investigations/{random}/request-evidence",
        "findings:comment",
        {"document_types": ["freight_invoice"], "note": "Needed"},
    ),
    (
        "POST",
        "/api/v1/cases/{random}/comparisons",
        "comparisons:run",
        {"original_document_id": "{random}", "test_document_id": "{random2}"},
    ),
    ("GET", "/api/v1/cases/{random}/comparisons", "comparisons:read", None),
    ("GET", "/api/v1/comparisons/{random}", "comparisons:read", None),
    ("POST", "/api/v1/comparisons/{random}/retry", "comparisons:run", None),
    (
        "PATCH",
        "/api/v1/comparisons/{random}/findings/{random}/review",
        "findings:review",
        {"status": "needs_more_evidence"},
    ),
    ("GET", "/api/v1/comparisons/{random}/findings/{random}/reviews", "comparisons:read", None),
    ("POST", "/api/v1/comparisons/{random}/exports", "comparisons:run", {"kind": "findings_json"}),
    ("GET", "/api/v1/comparisons/{random}/exports", "comparisons:read", None),
    ("GET", "/api/v1/comparison-exports/{random}/download", "comparisons:read", None),
    ("GET", "/api/v1/system/vlm-status", "comparisons:read", None),
]


def _body(body: dict[str, object] | None) -> dict[str, object] | None:
    if body is None:
        return None
    return {k: str(uuid.uuid4()) if v in ("{random}", "{random2}") else v for k, v in body.items()}


async def _accounts(client: httpx.AsyncClient) -> tuple[Account, dict[Role, Account]]:
    admin = await register(client, org_name="Matrix Org")
    by_role: dict[Role, Account] = {Role.ORG_ADMIN: admin}
    for role in Role:
        if role is Role.ORG_ADMIN:
            continue
        person = await register(client, org_name=f"Home of {role.value}")
        added = await client.post(
            f"/api/v1/organizations/{admin.organization_id}/members",
            headers=admin.headers,
            json={"email": person.email, "role": role.value},
        )
        assert added.status_code == 201
        by_role[role] = await login(client, person, organization_id=admin.organization_id)
    return admin, by_role


async def test_role_permission_matrix(client: httpx.AsyncClient) -> None:
    admin, by_role = await _accounts(client)
    fill: Callable[[str], str] = lambda p: p.format(  # noqa: E731
        org=admin.organization_id, random=uuid.uuid4()
    )
    failures: list[str] = []
    for role, account in by_role.items():
        for method, path, permission, body in ENDPOINTS:
            resp = await client.request(
                method, fill(path), headers=account.headers, json=_body(body)
            )
            allowed = permission in ROLE_PERMISSIONS[role]
            if allowed and resp.status_code == 403:
                failures.append(f"{role} {method} {path}: expected allowed, got 403")
            if not allowed and resp.status_code != 403:
                failures.append(f"{role} {method} {path}: expected 403, got {resp.status_code}")
    assert not failures, "\n".join(failures)
