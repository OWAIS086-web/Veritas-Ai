"""Regression: the request transaction must commit before the response is sent.

FastAPI runs a `yield` dependency's teardown after the response by default
(`scope="request"`). The session dependency's teardown is the commit, so a client that
reacted to a 2xx at once (the AI Agents screen refetching right after starting a run) could
read the database before the commit and see nothing. Every session dependency is therefore
`scope="function"`, and all of them share one scope so a request gets exactly one session
(FastAPI's dependency cache key includes the scope).
"""

from __future__ import annotations

import inspect
from typing import Any

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from app.main import create_app


def _yield_dependencies(dep: Dependant) -> list[Dependant]:
    found = []
    for sub in dep.dependencies:
        if inspect.isasyncgenfunction(sub.call) or inspect.isgeneratorfunction(sub.call):
            found.append(sub)
        found += _yield_dependencies(sub)
    return found


def _api_routes(routes: list[Any]) -> list[APIRoute]:
    """All API routes, including those of included routers (kept as wrappers since
    FastAPI 0.16x, which expose the router they wrap as `original_router`)."""
    out: list[APIRoute] = []
    for route in routes:
        if isinstance(route, APIRoute):
            out.append(route)
        elif hasattr(route, "original_router"):
            out += _api_routes(list(route.original_router.routes))
    return out


def test_every_session_dependency_commits_before_the_response() -> None:
    routes = _api_routes(list(create_app().routes))
    assert len(routes) > 50
    checked = 0
    for route in routes:
        for dep in _yield_dependencies(route.dependant):
            checked += 1
            assert dep.scope == "function", f"{route.path}: {dep.call.__name__} is {dep.scope}"
    assert checked > 50  # the session dependency is used across the API
