# VERITAS AI quality gate (run by the Kiro PostTaskExec hook and before marking a spec task done).
# Usage: pwsh -File scripts/quality-gate.ps1 [-SkipFrontend]
# Needs the Postgres and Redis containers: docker compose up -d postgres redis
param([switch]$SkipFrontend)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$results = [System.Collections.Generic.List[object]]::new()

function Step([string]$name, [string]$dir, [scriptblock]$cmd) {
    Write-Host "==> $name" -ForegroundColor Cyan
    Push-Location -LiteralPath $dir
    $output = & $cmd 2>&1 | Out-String
    $code = $LASTEXITCODE
    Pop-Location
    Write-Host $output.TrimEnd()
    $results.Add([pscustomobject]@{ Step = $name; Passed = ($code -eq 0); Output = $output })
}

$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

Step "ruff format --check" $backend { uv run ruff format --check app tests migrations scripts }
Step "ruff check" $backend { uv run ruff check app tests migrations scripts }
Step "mypy" $backend { uv run mypy }
Step "pytest (unit, property, integration)" $backend { uv run pytest -q -rs -p no:cacheprovider }
Step "OpenAPI contract" $backend { uv run python scripts/check_openapi.py }

# testing.md: a skipped integration suite is a gate failure, not a pass.
$pytest = $results | Where-Object Step -like "pytest*"
if ($pytest -and $pytest.Output -match "(\d+) skipped") {
    $pytest.Passed = $false
    Write-Host "pytest reported skipped tests; infrastructure-dependent tests must run." -ForegroundColor Red
}

if (-not $SkipFrontend) {
    Step "frontend typecheck" $frontend { npm run --silent typecheck }
    Step "frontend lint" $frontend { npm run --silent lint }
    Step "frontend tests" $frontend { npm run --silent test }
}

Write-Host ""
Write-Host "Quality gate summary" -ForegroundColor Cyan
foreach ($r in $results) {
    $mark = if ($r.Passed) { "PASS" } else { "FAIL" }
    $color = if ($r.Passed) { "Green" } else { "Red" }
    Write-Host ("  {0}  {1}" -f $mark, $r.Step) -ForegroundColor $color
}
if ($results | Where-Object { -not $_.Passed }) { exit 1 }
exit 0
