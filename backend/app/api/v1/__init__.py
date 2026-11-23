"""Version 1 API router."""

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    cases,
    documents,
    findings,
    forensics,
    graph,
    organizations,
    system,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(system.router)
api_router.include_router(cases.router)
api_router.include_router(documents.router)
api_router.include_router(findings.router)
api_router.include_router(graph.router)
api_router.include_router(forensics.router)
