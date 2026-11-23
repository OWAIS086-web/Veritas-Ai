"""Write the generated OpenAPI schema to backend/openapi.json (the committed contract)."""

from __future__ import annotations

from openapi_common import OPENAPI_PATH, dumps, generate


def main() -> None:
    OPENAPI_PATH.write_text(dumps(generate()), encoding="utf-8", newline="\n")
    print(f"wrote {OPENAPI_PATH}")


if __name__ == "__main__":
    main()
