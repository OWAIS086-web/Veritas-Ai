# Real outage check of the graph sync on the running stack: stop Neo4j, change a case,
# confirm the outbox keeps the change and the API falls back to Postgres, start Neo4j again,
# and confirm the worker applies the pending row. Uses SYNTHETIC DEMONSTRATION DATA.
param([string]$BaseUrl = "http://localhost:8080")
$ErrorActionPreference = "Stop"
$api = "$BaseUrl/api/v1"
$root = Join-Path (Split-Path -Parent $PSScriptRoot) "sample-data/shipment-case"
$suffix = [guid]::NewGuid().ToString("N").Substring(0, 8)
$tokens = Invoke-RestMethod "$api/auth/register" -Method Post -ContentType "application/json" -Body (@{
    email = "outage-$suffix@example.com"; password = "outage-check-$suffix"; full_name = "Outage Check"
    organization_name = "Outage Check $suffix" } | ConvertTo-Json)
$headers = @{ Authorization = "Bearer $($tokens.access_token)" }
$case = Invoke-RestMethod "$api/cases" -Method Post -Headers $headers -ContentType "application/json" `
    -Body (@{ title = "Outage check $suffix" } | ConvertTo-Json)
$form = @{ files = @("02_commercial_invoice.pdf", "03_customs_declaration.pdf" | ForEach-Object { Get-Item (Join-Path $root $_) }) }
$up = Invoke-RestMethod "$api/cases/$($case.id)/documents" -Method Post -Headers $headers -Form $form
do { Start-Sleep 2; $job = Invoke-RestMethod "$api/jobs/$($up.job_id)" -Headers $headers } while ($job.status -notin "succeeded", "failed")
do { Start-Sleep 2; $g = Invoke-RestMethod "$api/cases/$($case.id)/graph" -Headers $headers } while ($g.source -ne "neo4j")
Write-Host "1. synced: source=$($g.source) nodes=$($g.total_nodes) edges=$($g.total_edges)"

docker compose stop neo4j | Out-Null
$rebuilt = Invoke-RestMethod "$api/cases/$($case.id)/graph/rebuild" -Method Post -Headers $headers
Start-Sleep 20   # at least one scheduled drain runs while Neo4j is down
$health = Invoke-RestMethod "$api/system/health"
$g = Invoke-RestMethod "$api/cases/$($case.id)/graph" -Headers $headers
Write-Host "2. neo4j stopped: health.graph=$($health.graph.status) pending=$($health.graph.outbox_pending) api source=$($g.source) edges=$($g.total_edges) (rebuild wrote $($rebuilt.relationships))"
if ($g.source -ne "postgres" -or $health.graph.outbox_pending -lt 1) { throw "expected a Postgres fallback and a pending outbox row" }

docker compose start neo4j | Out-Null
$started = Get-Date
do { Start-Sleep 3; $g = Invoke-RestMethod "$api/cases/$($case.id)/graph" -Headers $headers } while ($g.source -ne "neo4j" -and ((Get-Date) - $started).TotalSeconds -lt 600)
$health = Invoke-RestMethod "$api/system/health"
Write-Host "3. neo4j started: api source=$($g.source) edges=$($g.total_edges) after $([int]((Get-Date) - $started).TotalSeconds) s; pending=$($health.graph.outbox_pending) dead=$($health.graph.outbox_dead)"
if ($g.source -ne "neo4j") { throw "the pending row was not applied after Neo4j came back" }
