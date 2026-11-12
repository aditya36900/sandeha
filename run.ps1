<#
.SYNOPSIS
  Start the Sandeha station on Windows.
.EXAMPLE
  .\run.ps1            # station + built dashboard on http://localhost:8000
  .\run.ps1 -Dev       # also starts Vite with hot reload on http://localhost:5173 (edit frontend/src live)
  .\run.ps1 -Seed      # after start, seed two demo product lines (pcb3, pcb4) with a production run
  .\run.ps1 -Port 8080
#>
param([switch]$Dev, [switch]$Seed, [int]$Port = 8000)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$vpy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) { Write-Host "No .venv found: run .\setup.ps1 first." -ForegroundColor Red; exit 1 }

if ($Dev) {
    Write-Host "Starting Vite dev server (http://localhost:5173) in a new window..." -ForegroundColor Yellow
    $env:SANDEHA_API = "http://127.0.0.1:$Port"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\frontend'; npm run dev"
}
if ($Seed) {
    Write-Host "Will seed demo lines once the station is up (about 2 minutes)..." -ForegroundColor Yellow
    Start-Process $vpy -ArgumentList "backend\scripts\seed_demo.py" -WorkingDirectory $PSScriptRoot
}
Write-Host "Sandeha station on http://localhost:$Port  (Ctrl+C to stop)" -ForegroundColor Green
Set-Location backend
& $vpy -m uvicorn sandeha.api:app --host 127.0.0.1 --port $Port
