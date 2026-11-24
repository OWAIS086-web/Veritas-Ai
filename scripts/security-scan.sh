#!/usr/bin/env bash
# VERITAS AI security scan (Linux/macOS twin of security-scan.ps1).
# Usage: scripts/security-scan.sh
# Needs Docker (gitleaks, semgrep), uv (pip-audit, bandit) and npm. Exceptions: docs/security.md.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
declare -a NAMES=() CODES=()

step() {
  local name="$1" dir="$2"; shift 2
  printf '\033[36m==> %s\033[0m\n' "$name"
  (cd "$dir" && "$@"); local code=$?
  NAMES+=("$name"); CODES+=("$code")
}

gitleaks_scan() {
  # Exactly what git would commit: tracked and untracked, not ignored (.env stays out).
  local scan; scan="$(mktemp -d)"
  git ls-files -co --exclude-standard -z | while IFS= read -r -d '' f; do
    mkdir -p "$scan/$(dirname "$f")" && cp -- "$f" "$scan/$f"
  done
  docker run --rm -v "$scan:/scan" zricethezav/gitleaks:latest dir /scan --no-banner --redact
  local code=$?
  rm -rf "$scan"
  return "$code"
}

pip_audit() {
  local req; req="$(mktemp)"
  uv export --frozen --all-extras --no-emit-project --no-hashes --format requirements-txt -o "$req" >/dev/null
  uvx pip-audit -r "$req" --disable-pip --no-deps --progress-spinner off
  local code=$?
  rm -f "$req"
  return "$code"
}

step "gitleaks (committable files)" "$ROOT" gitleaks_scan
step "pip-audit (uv.lock, all extras)" "$ROOT/backend" pip_audit
step "npm audit (high and critical)" "$ROOT/frontend" npm audit --audit-level=high
step "semgrep (project rules + p/python)" "$ROOT" docker run --rm -v "$ROOT:/src" -w /src \
  semgrep/semgrep:latest semgrep scan --config .semgrep/veritas.yml --config p/python --error \
  --metrics=off --quiet backend/app backend/migrations
step "bandit (medium and above)" "$ROOT/backend" uvx bandit -r app -ll -q

echo; echo "Security scan summary"
FAILED=0
for i in "${!NAMES[@]}"; do
  if [ "${CODES[$i]}" -eq 0 ]; then echo "  PASS  ${NAMES[$i]}"; else echo "  FAIL  ${NAMES[$i]}"; FAILED=1; fi
done
exit "$FAILED"
