"""Role → permission map. The only place role capabilities are defined."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ORG_ADMIN = "org_admin"
    INVESTIGATION_MANAGER = "investigation_manager"
    INVESTIGATOR = "investigator"
    REVIEWER = "reviewer"
    READ_ONLY_ANALYST = "read_only_analyst"


ROLE_LABELS: dict[Role, str] = {
    Role.ORG_ADMIN: "Organization Admin",
    Role.INVESTIGATION_MANAGER: "Investigation Manager",
    Role.INVESTIGATOR: "Investigator",
    Role.REVIEWER: "Reviewer",
    Role.READ_ONLY_ANALYST: "Read-only Analyst",
}

ALL_PERMISSIONS: frozenset[str] = frozenset(
    {
        "org:read",
        "org:update",
        "members:read",
        "members:manage",
        "audit:read",
        "stats:read",
        "jobs:read",
        "system:ping",
        "cases:read",
        "cases:write",
        "cases:delete",
        "documents:read",
        "documents:upload",
        "documents:process",
        "findings:read",
        "findings:run",
        "findings:comment",
        "findings:review",
        "graph:read",
        "graph:rebuild",
        "forensics:read",
    }
)

_READ = frozenset(
    {
        "org:read",
        "members:read",
        "stats:read",
        "jobs:read",
        "cases:read",
        "documents:read",
        "findings:read",
        "graph:read",
        "forensics:read",
    }
)
_WORK = frozenset(
    {
        "cases:write",
        "documents:upload",
        "documents:process",
        "findings:run",
        "findings:comment",
        "graph:rebuild",
    }
)

ROLE_PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.ORG_ADMIN: ALL_PERMISSIONS,
    Role.INVESTIGATION_MANAGER: _READ
    | _WORK
    | {"audit:read", "system:ping", "cases:delete", "findings:review"},
    Role.INVESTIGATOR: _READ | _WORK,
    Role.REVIEWER: _READ | {"findings:review", "findings:comment"},
    Role.READ_ONLY_ANALYST: _READ,
}


def permissions_for(role: str) -> frozenset[str]:
    try:
        return ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return frozenset()


def has_permission(role: str, permission: str) -> bool:
    return permission in permissions_for(role)
