#!/usr/bin/env bash
# VERITAS AI quality gate (Linux/macOS twin of quality-gate.ps1).
# Usage: scripts/quality-gate.sh [--skip-frontend]
# Needs the Postgres and Redis containers: docker compose up -d postgres redis
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKIP_FRONTEND=0
[ "${1:-}" = "--skip-frontend" ] && SKIP_FRONTEND=1
declare -a NAMES=() CODES=()

step() {
  local name="$1" dir="$2"; shift 2
  printf '\033[36m==> %s\033[0m\n' "$name"
  local out
  out="$(cd "$dir" && "$@" 2>&1)"; local code=$?
  echo "$out"
  if [[ "$name" == pytest* ]] && grep -Eq '[0-9]+ skipped' <<<"$out"; then
    echo "pytest reported skipped tests; infrastructure-dependent tests must run."
    code=1
  fi
  NAMES+=("$name"); CODES+=("$code")
}

step "ruff format --check" "$ROOT/backend" uv run ruff format --check app tests migrations scripts
step "ruff check" "$ROOT/backend" uv run ruff check app tests migrations scripts
step "mypy" "$ROOT/backend" uv run mypy
step "pytest (unit, property, integration)" "$ROOT/backend" uv run pytest -q -rs -p no:cacheprovider
step "OpenAPI contract" "$ROOT/backend" uv run python scripts/check_openapi.py
if [ "$SKIP_FRONTEND" -eq 0 ]; then
  step "frontend typecheck" "$ROOT/frontend" npm run --silent typecheck
  step "frontend lint" "$ROOT/frontend" npm run --silent lint
  step "frontend tests" "$ROOT/frontend" npm run --silent test
fi

echo; echo "Quality gate summary"
FAILED=0
for i in "${!NAMES[@]}"; do
  if [ "${CODES[$i]}" -eq 0 ]; then echo "  PASS  ${NAMES[$i]}"; else echo "  FAIL  ${NAMES[$i]}"; FAILED=1; fi
done
exit "$FAILED"
