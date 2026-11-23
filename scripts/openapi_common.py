"""Shared helper: build the OpenAPI document without connecting to any service."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
OPENAPI_PATH = BACKEND / "openapi.json"


def generate() -> dict[str, Any]:
    # Schema generation needs valid settings but never opens a connection.
    os.environ.setdefault("VERITAS_DATABASE_URL", "postgresql+asyncpg://schema:gen@127.0.0.1:1/x")
    os.environ.setdefault("VERITAS_REDIS_URL", "redis://127.0.0.1:1/0")
    os.environ.setdefault("VERITAS_JWT_SECRET", "openapi-generation-only-not-a-secret")
    sys.path.insert(0, str(BACKEND))
    from app.main import create_app

    schema: dict[str, Any] = create_app().openapi()
    return schema


def dumps(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"
