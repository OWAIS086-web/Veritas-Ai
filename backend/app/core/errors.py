"""Domain errors and their RFC 7807 problem+json rendering."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger, request_id_var

PROBLEM_JSON = "application/problem+json"
logger = get_logger(__name__)


class DomainError(Exception):
    status_code = 400
    title = "Bad request"

    def __init__(self, detail: str | None = None, headers: dict[str, str] | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.headers = headers


class NotFoundError(DomainError):
    status_code = 404
    title = "Not found"


class ConflictError(DomainError):
    status_code = 409
    title = "Conflict"


class AuthenticationError(DomainError):
    status_code = 401
    title = "Authentication required"


class PermissionDeniedError(DomainError):
    status_code = 403
    title = "Permission denied"


class ValidationFailedError(DomainError):
    status_code = 422
    title = "Validation failed"


class RateLimitedError(DomainError):
    status_code = 429
    title = "Too many requests"


class ServiceUnavailableError(DomainError):
    status_code = 503
    title = "Service unavailable"


def problem(
    request: Request,
    status: int,
    title: str,
    detail: str,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
    }
    rid = request_id_var.get()
    if rid:
        body["request_id"] = rid
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(request: Request, exc: DomainError) -> JSONResponse:
        return problem(request, exc.status_code, exc.title, exc.detail, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": [str(p) for p in err.get("loc", ())], "msg": err.get("msg", "")}
            for err in exc.errors()
        ]
        return problem(
            request, 422, "Validation failed", "Request validation failed", extra={"errors": errors}
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        title = "Not found" if exc.status_code == 404 else "HTTP error"
        return problem(
            request, exc.status_code, title, str(exc.detail), headers=getattr(exc, "headers", None)
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", extra={"path": request.url.path})
        return problem(
            request,
            500,
            "Internal server error",
            "An unexpected error occurred. Quote the request_id when reporting it.",
        )
