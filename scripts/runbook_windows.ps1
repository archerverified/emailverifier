# =============================================================================
# Lead Validator - Windows Testing Runbook
# =============================================================================
# Run this script in PowerShell to test the deployed Lead Validator API.
# Usage: .\scripts\runbook_windows.ps1
#
# Prerequisites:
# - curl.exe available (comes with Windows 10+)
# - API key from VPS deployment
# =============================================================================

$Domain = "validator.2ndimpression.co"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Lead Validator - Windows Testing" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# 1. DNS check
Write-Host "1. DNS Resolution Check..." -ForegroundColor Yellow
try {
    $dns = Resolve-DnsName $Domain -ErrorAction Stop
    Write-Host "   $Domain -> $($dns.IPAddress)" -ForegroundColor Green
} catch {
    Write-Host "   ERROR: DNS resolution failed" -ForegroundColor Red
    Write-Host "   Make sure A record points to VPS IP" -ForegroundColor Red
}
Write-Host ""

# 2. HTTPS health check
Write-Host "2. HTTPS Health Check..." -ForegroundColor Yellow
try {
    $healthResponse = curl.exe -s "https://$Domain/health" 2>$null
    if ($healthResponse -match "ok") {
        Write-Host "   Health: $healthResponse" -ForegroundColor Green
    } else {
        Write-Host "   WARNING: Unexpected response: $healthResponse" -ForegroundColor Yellow
    }
} catch {
    Write-Host "   ERROR: Health check failed" -ForegroundColor Red
}
Write-Host ""

# 3. Auth check (should be 401 without key)
Write-Host "3. Auth Check (expect 401 Unauthorized)..." -ForegroundColor Yellow
$authResponse = curl.exe -s -o NUL -w "%{http_code}" -X POST "https://$Domain/verify" 2>$null
if ($authResponse -eq "401") {
    Write-Host "   HTTP $authResponse - Correctly rejected (no API key)" -ForegroundColor Green
} else {
    Write-Host "   HTTP $authResponse - Unexpected status code" -ForegroundColor Yellow
}
Write-Host ""

# 4. Prompt for API key
Write-Host "4. API Key Test..." -ForegroundColor Yellow
$ApiKey = Read-Host "   Enter your API key (from VPS deployment)"

if ([string]::IsNullOrWhiteSpace($ApiKey)) {
    Write-Host "   Skipping API key tests (no key provided)" -ForegroundColor Yellow
} else {
    # Test schema endpoint with key
    Write-Host "   Testing /schema with API key..." -ForegroundColor Yellow
    $schemaResponse = curl.exe -s -H "X-API-Key: $ApiKey" "https://$Domain/schema" 2>$null
    if ($schemaResponse -match "endpoints") {
        Write-Host "   Schema endpoint working!" -ForegroundColor Green
    } else {
        Write-Host "   WARNING: Unexpected response" -ForegroundColor Yellow
    }
    Write-Host ""

    # 5. Upload test CSV
    Write-Host "5. Upload Test..." -ForegroundColor Yellow
    $tempCsv = "$env:TEMP\test_validator.csv"
    "email`ntest@example.com" | Out-File -Encoding ascii $tempCsv
    Write-Host "   Created test CSV: $tempCsv"

    $uploadResponse = curl.exe -s -H "X-API-Key: $ApiKey" -F "file=@$tempCsv" "https://$Domain/verify" 2>$null
    if ($uploadResponse -match "job_id") {
        Write-Host "   Upload successful!" -ForegroundColor Green
        Write-Host "   Response: $uploadResponse"
    } else {
        Write-Host "   WARNING: Unexpected response: $uploadResponse" -ForegroundColor Yellow
    }

    # Cleanup
    Remove-Item $tempCsv -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Testing Complete" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Verify Checklist:" -ForegroundColor White
Write-Host "  [ ] https://$Domain/        -> HTML UI loads"
Write-Host "  [ ] https://$Domain/health  -> {`"status`":`"ok`"}"
Write-Host "  [ ] POST /verify without key -> 401"
Write-Host "  [ ] POST /verify with key    -> job_id returned"
Write-Host ""
