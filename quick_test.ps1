# Quick Test Script for Lead Validator
# Run this after cloning the repo to verify everything works

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Lead Validator - Quick Test Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if we're in the right directory
if (-not (Test-Path "backend\app.py")) {
    Write-Host "[ERROR] Please run this script from the project root directory" -ForegroundColor Red
    exit 1
}

Write-Host "[1/5] Checking Python installation..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "      Found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "      [ERROR] Python not found. Please install Python 3.8+" -ForegroundColor Red
    exit 1
}

Write-Host "[2/5] Setting up virtual environment..." -ForegroundColor Yellow
if (-not (Test-Path "backend\venv")) {
    cd backend
    python -m venv venv
    cd ..
    Write-Host "      Created virtual environment" -ForegroundColor Green
} else {
    Write-Host "      Virtual environment already exists" -ForegroundColor Green
}

Write-Host "[3/5] Installing dependencies..." -ForegroundColor Yellow
cd backend
.\venv\Scripts\Activate.ps1
pip install -q -r requirements.txt
if ($LASTEXITCODE -eq 0) {
    Write-Host "      Dependencies installed" -ForegroundColor Green
} else {
    Write-Host "      [ERROR] Failed to install dependencies" -ForegroundColor Red
    exit 1
}

Write-Host "[4/5] Running test suite..." -ForegroundColor Yellow
$env:VALIDATOR_MODE = "mock"
$env:TESTING = "1"
$testOutput = pytest -v --tb=short 2>&1 | Out-String
if ($LASTEXITCODE -eq 0) {
    $passedCount = ($testOutput | Select-String "(\d+) passed").Matches.Groups[1].Value
    Write-Host "      All $passedCount tests passed!" -ForegroundColor Green
} else {
    Write-Host "      [ERROR] Some tests failed" -ForegroundColor Red
    Write-Host $testOutput
    exit 1
}

Write-Host "[5/5] Running smoke test..." -ForegroundColor Yellow
cd ..
$smokeOutput = python scripts\smoke_test.py 2>&1 | Out-String
if ($LASTEXITCODE -eq 0) {
    Write-Host "      Smoke test passed!" -ForegroundColor Green
} else {
    Write-Host "      [ERROR] Smoke test failed" -ForegroundColor Red
    Write-Host $smokeOutput
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "SUCCESS! All tests passed!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Start backend:  cd backend; .\venv\Scripts\Activate.ps1; python app.py"
Write-Host "  2. Open browser:   http://localhost:5050"
Write-Host "  3. Upload CSV:     Drag Fortune500leads.csv to the drop zone"
Write-Host ""
Write-Host "OR use Docker:" -ForegroundColor Yellow
Write-Host "  docker compose up --build"
Write-Host ""
Write-Host "For detailed testing guide, see TESTING_GUIDE.md" -ForegroundColor Cyan
