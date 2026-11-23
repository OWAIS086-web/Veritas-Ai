# VERITAS AI smoke test against the running stack (through Nginx).
# Usage: pwsh -File scripts/smoke.ps1 [-BaseUrl http://localhost:8080]
param([string]$BaseUrl = "http://localhost:8080")
$ErrorActionPreference = "Stop"
$api = "$BaseUrl/api/v1"
$failures = 0

function Check([string]$name, [scriptblock]$test) {
    try {
        $detail = & $test
        Write-Host "PASS  $name $detail" -ForegroundColor Green
    } catch {
        Write-Host "FAIL  $name : $($_.Exception.Message)" -ForegroundColor Red
        $script:failures++
    }
}

Check "nginx /healthz" { (Invoke-WebRequest "$BaseUrl/healthz" -UseBasicParsing).StatusCode | Out-Null }
Check "api health (database + redis)" {
    $h = Invoke-RestMethod "$api/system/health"
    if ($h.status -ne "ok") { throw "status=$($h.status)" }
}
Check "SPA served with security headers" {
    $r = Invoke-WebRequest "$BaseUrl/" -UseBasicParsing
    if ($r.Content -notmatch 'id="root"') { throw "index.html not served" }
    if (-not $r.Headers["Content-Security-Policy"]) { throw "missing CSP" }
}

$suffix = [guid]::NewGuid().ToString("N").Substring(0, 10)
$email = "smoke-$suffix@example.com"
$password = "smoke-password-$suffix"
$script:tokens = $null

Check "register" {
    $body = @{ email = $email; password = $password; full_name = "Smoke Test"; organization_name = "Smoke Org $suffix" } | ConvertTo-Json
    $script:tokens = Invoke-RestMethod "$api/auth/register" -Method Post -ContentType "application/json" -Body $body
}
Check "login" {
    $body = @{ email = $email; password = $password } | ConvertTo-Json
    $script:tokens = Invoke-RestMethod "$api/auth/login" -Method Post -ContentType "application/json" -Body $body
}
$headers = @{ Authorization = "Bearer $($script:tokens.access_token)" }
Check "auth/me" {
    $me = Invoke-RestMethod "$api/auth/me" -Headers $headers
    if ($me.user.email -ne $email -or $me.role -ne "org_admin") { throw "unexpected profile" }
}
Check "wrong password is 401" {
    try {
        Invoke-RestMethod "$api/auth/login" -Method Post -ContentType "application/json" -Body (@{ email = $email; password = "wrong-password-1" } | ConvertTo-Json) | Out-Null
        throw "expected 401"
    } catch [Microsoft.PowerShell.Commands.HttpResponseException] {
        if ($_.Exception.Response.StatusCode.value__ -ne 401) { throw }
    }
}
Check "worker processes a real job (API -> Redis -> Celery -> Postgres)" {
    $job = Invoke-RestMethod "$api/system/ping-job" -Method Post -Headers $headers
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        $job = Invoke-RestMethod "$api/jobs/$($job.id)" -Headers $headers
        if ($job.status -in @("succeeded", "failed")) { break }
    }
    if ($job.status -ne "succeeded") { throw "job status=$($job.status) error=$($job.error)" }
    "(worker $($job.result.worker), $($job.result.db_roundtrip_ms) ms)"
}
Check "document pipeline (upload -> S3 store -> worker OCR/parse -> extraction)" {
    $case = Invoke-RestMethod "$api/cases" -Method Post -Headers $headers -ContentType "application/json" `
        -Body (@{ title = "Smoke case $suffix"; objective = "Smoke test" } | ConvertTo-Json)
    $pdf = Join-Path (Split-Path -Parent $PSScriptRoot) "sample-data/shipment-case/02_commercial_invoice.pdf"
    $form = @{ files = Get-Item -LiteralPath $pdf }
    $up = Invoke-RestMethod "$api/cases/$($case.id)/documents" -Method Post -Headers $headers -Form $form
    $docId = $up.results[0].document_id
    if ($up.results[0].status -ne "accepted") { throw "upload status=$($up.results[0].status)" }
    for ($i = 0; $i -lt 240; $i++) {
        Start-Sleep -Seconds 1
        $doc = Invoke-RestMethod "$api/documents/$docId" -Headers $headers
        if ($doc.status -in @("completed", "failed")) { break }
    }
    if ($doc.status -ne "completed") { throw "document status=$($doc.status) error=$($doc.error)" }
    $ext = Invoke-RestMethod "$api/documents/$docId/extractions" -Headers $headers
    $total = $ext.fields | Where-Object name -eq "total_amount"
    if ($total.normalized_value.amount -ne "48000.00" -or -not $total.bbox) { throw "unexpected total: $($total | ConvertTo-Json -Compress)" }
    $script:smokeCase = $case.id
    "(USD $($total.normalized_value.amount) on page $($total.page_number), $([int]$i)s)"
}
Check "cross-document comparison (second document -> worker -> findings with evidence)" {
    $pdf = Join-Path (Split-Path -Parent $PSScriptRoot) "sample-data/shipment-case/03_customs_declaration.pdf"
    $up = Invoke-RestMethod "$api/cases/$($script:smokeCase)/documents" -Method Post -Headers $headers -Form @{ files = Get-Item -LiteralPath $pdf }
    $docId = $up.results[0].document_id
    for ($i = 0; $i -lt 240; $i++) {
        Start-Sleep -Seconds 1
        $job = Invoke-RestMethod "$api/jobs/$($up.job_id)" -Headers $headers
        if ($job.status -in @("succeeded", "failed")) { break }
    }
    if ($job.status -ne "succeeded") { throw "processing job status=$($job.status)" }
    $findings = Invoke-RestMethod "$api/cases/$($script:smokeCase)/findings" -Headers $headers
    $money = @($findings | Where-Object type -eq "financial_discrepancy")
    if ($money.Count -ne 1 -or $money[0].difference -ne "20000.00" -or $money[0].evidence_count -ne 2) {
        throw "unexpected findings: $($findings | ConvertTo-Json -Compress -Depth 3)"
    }
    "(USD $($money[0].difference) across $($money[0].evidence_count) documents, $(@($findings).Count) findings)"
}
Check "evidence graph (Postgres rows -> outbox -> worker -> Neo4j)" {
    for ($i = 0; $i -lt 90; $i++) {
        $graph = Invoke-RestMethod "$api/cases/$($script:smokeCase)/graph" -Headers $headers
        if ($graph.source -eq "neo4j") { break }
        Start-Sleep -Seconds 1
    }
    if ($graph.source -ne "neo4j") { throw "graph still served from $($graph.source) after 90 s" }
    $contradicts = @($graph.edges | Where-Object type -eq "CONTRADICTS")
    if ($contradicts.Count -ne 1 -or -not $contradicts[0].finding_id) { throw "unexpected CONTRADICTS edges: $($contradicts.Count)" }
    if (@($graph.edges | Where-Object { -not $_.evidence_ids }).Count) { throw "edge without evidence" }
    "($($graph.total_nodes) nodes, $($graph.total_edges) relationships, $([int]$i) s to sync)"
}
Check "document forensics (worker forensics stage -> runs with limitations)" {
    $response = Invoke-RestMethod "$api/cases/$($script:smokeCase)/forensics" -Headers $headers
    $summary = @($response | ForEach-Object { $_ })
    if ($summary.Count -ne 2) { throw "expected 2 documents, got $($summary.Count)" }
    foreach ($row in $summary) {
        $run = Invoke-RestMethod "$api/documents/$($row.document_id)/forensics" -Headers $headers
        if ($run.status -ne "succeeded") { throw "$($row.filename): forensic status=$($run.status)" }
        if (-not ($run.limitations -match "does not establish document alteration")) { throw "$($row.filename): limitation missing" }
    }
    "($(@($summary | ForEach-Object { $_.anomalies } | Measure-Object -Sum).Sum) anomalies across $($summary.Count) unaltered documents)"
}
Check "audit log recorded the session" {
    $logs = Invoke-RestMethod "$api/audit-logs" -Headers $headers
    $actions = $logs.items.action
    if ($actions -notcontains "auth.register" -or $actions -notcontains "auth.login") { throw "missing entries" }
}

if ($failures -gt 0) { Write-Host "$failures smoke check(s) failed" -ForegroundColor Red; exit 1 }
Write-Host "All smoke checks passed" -ForegroundColor Green
