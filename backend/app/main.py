"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIdMiddleware

API_DESCRIPTION = (
    "VERITAS AI: Autonomous Document Investigation & Truth Intelligence Platform. "
    "Errors are returned as RFC 7807 `application/problem+json`. Resources of another "
    "organization always return 404."
)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="VERITAS AI API",
        version="0.1.0",
        description=API_DESCRIPTION,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
