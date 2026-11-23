"""Version 1 API router."""

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    cases,
    doccompare,
    documents,
    findings,
    forensics,
    graph,
    investigations,
    organizations,
    reports,
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
api_router.include_router(investigations.router)
api_router.include_router(reports.router)
api_router.include_router(doccompare.router)
