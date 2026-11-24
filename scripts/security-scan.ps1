# VERITAS AI security scan (enterprise-security 3.4, 4.1, 4.2).
# Usage: pwsh -File scripts/security-scan.ps1
# Needs Docker (gitleaks, semgrep), uv (pip-audit, bandit) and npm. Exceptions: docs/security.md.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$results = [System.Collections.Generic.List[object]]::new()

function Step([string]$name, [string]$dir, [scriptblock]$cmd) {
    Write-Host "==> $name" -ForegroundColor Cyan
    Push-Location -LiteralPath $dir
    $output = & $cmd 2>&1 | Out-String
    $code = $LASTEXITCODE
    Pop-Location
    Write-Host $output.TrimEnd()
    $results.Add([pscustomobject]@{ Step = $name; Passed = ($code -eq 0) })
}

# gitleaks scans exactly what git would commit: tracked and untracked, not ignored (.env stays out).
$scan = Join-Path ([IO.Path]::GetTempPath()) ("veritas-scan-" + [guid]::NewGuid().ToString("N"))
Step "gitleaks (committable files)" $root {
    git -c safe.directory='*' ls-files -co --exclude-standard | ForEach-Object {
        $target = Join-Path $scan $_
        New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
        Copy-Item -LiteralPath $_ -Destination $target
    }
    docker run --rm -v "${scan}:/scan" zricethezav/gitleaks:latest dir /scan --no-banner --redact
}
Remove-Item -Recurse -Force -LiteralPath $scan -ErrorAction SilentlyContinue

$req = Join-Path ([IO.Path]::GetTempPath()) "veritas-requirements.txt"
Step "pip-audit (uv.lock, all extras)" $backend {
    uv export --frozen --all-extras --no-emit-project --no-hashes --format requirements-txt -o $req | Out-Null
    uvx pip-audit -r $req --disable-pip --no-deps --progress-spinner off
}
Step "npm audit (high and critical)" $frontend { npm audit --audit-level=high }
Step "semgrep (project rules + p/python)" $root {
    docker run --rm -v "${root}:/src" -w /src semgrep/semgrep:latest semgrep scan `
        --config .semgrep/veritas.yml --config p/python --error --metrics=off --quiet `
        backend/app backend/migrations
}
Step "bandit (medium and above)" $backend { uvx bandit -r app -ll -q }

Write-Host ""
Write-Host "Security scan summary" -ForegroundColor Cyan
foreach ($r in $results) {
    $mark = if ($r.Passed) { "PASS" } else { "FAIL" }
    $color = if ($r.Passed) { "Green" } else { "Red" }
    Write-Host ("  {0}  {1}" -f $mark, $r.Step) -ForegroundColor $color
}
if ($results | Where-Object { -not $_.Passed }) { exit 1 }
exit 0
