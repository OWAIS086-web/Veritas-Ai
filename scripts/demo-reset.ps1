# Reset the demo organization and seed it from sample-data/shipment-case (public API only).
# Usage: pwsh -File scripts/demo-reset.ps1 [-BaseUrl http://localhost:8080]
# Needs the stack (docker compose up -d) and VERITAS_DEMO_EMAIL / VERITAS_DEMO_PASSWORD in .env.
param([string]$BaseUrl = "http://localhost:8080")
$root = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath (Join-Path $root "backend")
try {
    uv run python scripts/demo_seed.py --base-url $BaseUrl
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
