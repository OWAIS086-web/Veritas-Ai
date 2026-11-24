#!/usr/bin/env bash
# Reset the demo organization and seed it from sample-data/shipment-case (public API only).
# Usage: scripts/demo-reset.sh [base-url]   (default http://localhost:8080)
# Needs the stack (docker compose up -d) and VERITAS_DEMO_EMAIL / VERITAS_DEMO_PASSWORD in .env.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
exec uv run python scripts/demo_seed.py --base-url "${1:-http://localhost:8080}"
