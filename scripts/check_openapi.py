"""Fail if the generated OpenAPI schema differs from the committed backend/openapi.json.

Prints the paths and schemas that changed, and marks removed endpoints as breaking.
Run `uv run python scripts/export_openapi.py` after an intentional API change.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from openapi_common import OPENAPI_PATH, dumps, generate


def _operations(schema: dict[str, Any]) -> set[str]:
    return {
        f"{method.upper()} {path}"
        for path, item in schema.get("paths", {}).items()
        for method in item
    }


def main() -> int:
    current = generate()
    if not OPENAPI_PATH.exists():
        print(f"missing {OPENAPI_PATH}; run scripts/export_openapi.py", file=sys.stderr)
        return 1
    committed = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    if dumps(current) == dumps(committed):
        print("OpenAPI contract matches backend/openapi.json")
        return 0

    removed = sorted(_operations(committed) - _operations(current))
    added = sorted(_operations(current) - _operations(committed))
    old_schemas = committed.get("components", {}).get("schemas", {})
    new_schemas = current.get("components", {}).get("schemas", {})
    changed = sorted(
        k for k in old_schemas.keys() & new_schemas.keys() if old_schemas[k] != new_schemas[k]
    )
    print("OpenAPI contract differs from backend/openapi.json:", file=sys.stderr)
    for op in removed:
        print(f"  BREAKING removed: {op}", file=sys.stderr)
    for op in added:
        print(f"  added: {op}", file=sys.stderr)
    for name in changed:
        print(f"  schema changed: {name}", file=sys.stderr)
    print("If intended, run: uv run python scripts/export_openapi.py", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
