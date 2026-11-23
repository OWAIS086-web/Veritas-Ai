# Live check of the configured model provider (VERITAS_LLM_*) on the running stack.
# Uploads the synthetic shipment case (SYNTHETIC DEMONSTRATION DATA), waits for processing,
# and reports per document: extraction method, model, verified and rejected fields, and timing.
param(
    [string]$BaseUrl = "http://localhost:8080",
    [string[]]$Files = @(
        "shipment-case/01_purchase_order.pdf", "shipment-case/02_commercial_invoice.pdf",
        "shipment-case/03_customs_declaration.pdf", "shipment-case/04_insurance_certificate.pdf",
        "shipment-case/05_payment_receipt.pdf", "shipment-case/06_packing_list.pdf",
        "shipment-case/07_bill_of_lading.pdf"
    ),
    # Use the single-document format variants (scanned PDF, images, DOCX, XLSX, CSV, EML).
    [switch]$Variants
)
$ErrorActionPreference = "Stop"
if ($Variants) {
    $Files = @(
        "format-variants/commercial_invoice_scanned.pdf", "format-variants/purchase_order.png",
        "format-variants/payment_receipt.jpg", "format-variants/bill_of_lading.tiff",
        "format-variants/commercial_invoice.docx", "format-variants/packing_list.xlsx",
        "format-variants/commercial_invoice.csv", "format-variants/payment_advice.eml"
    )
}
$api = "$BaseUrl/api/v1"
$root = Join-Path (Split-Path -Parent $PSScriptRoot) "sample-data"
$suffix = [guid]::NewGuid().ToString("N").Substring(0, 8)
$tokens = Invoke-RestMethod "$api/auth/register" -Method Post -ContentType "application/json" -Body (@{
    email = "live-$suffix@example.com"; password = "live-check-$suffix"; full_name = "Live Check"
    organization_name = "Live Model Check $suffix" } | ConvertTo-Json)
$headers = @{ Authorization = "Bearer $($tokens.access_token)" }
$case = Invoke-RestMethod "$api/cases" -Method Post -Headers $headers -ContentType "application/json" `
    -Body (@{ title = "Live model check $suffix" } | ConvertTo-Json)

$form = @{ files = @($Files | ForEach-Object { Get-Item -LiteralPath (Join-Path $root $_) }) }
$started = Get-Date
$up = Invoke-RestMethod "$api/cases/$($case.id)/documents" -Method Post -Headers $headers -Form $form
do {
    Start-Sleep -Seconds 2
    $job = Invoke-RestMethod "$api/jobs/$($up.job_id)" -Headers $headers
} while ($job.status -notin @("succeeded", "failed") -and ((Get-Date) - $started).TotalMinutes -lt 30)
$elapsed = [int]((Get-Date) - $started).TotalSeconds
Write-Host "Job $($job.status) in $elapsed s"

$docs = Invoke-RestMethod "$api/cases/$($case.id)/documents" -Headers $headers
$rows = foreach ($d in $docs) {
    $ext = Invoke-RestMethod "$api/documents/$($d.id)/extractions" -Headers $headers
    $extract = $d.stages | Where-Object stage -eq "extract"
    $byMethod = $ext.fields | Group-Object method | ForEach-Object { "$($_.Name)=$($_.Count)" }
    $rejected = $ext.fields | Where-Object status -ne "extracted" |
        ForEach-Object { "$($_.name):$($_.rejection_reason)" }
    [pscustomobject]@{
        file = $d.original_filename; status = $d.status; run = $ext.method; model = $ext.model_version
        extract_ms = $extract.metrics.duration_ms; fields = ($byMethod -join " ")
        uncertain = ($rejected -join ", ")
        llm_rejected = ($ext.notes.llm_rejected | ConvertTo-Json -Compress)
        replaced_by_rules = ($ext.notes.replaced_by_rules -join ", ")
    }
}
$rows | Format-List
$findings = Invoke-RestMethod "$api/cases/$($case.id)/findings" -Headers $headers
Write-Host "Findings:"
$findings | ForEach-Object { "  $($_.type) $($_.currency) $($_.difference) evidence=$($_.evidence_count)" }
