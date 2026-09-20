# TAUROS Cognitive OS — avvio API (Windows)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .\.venv\Scripts\Activate.ps1)) {
  Write-Error "Venv assente. Esegui prima .\install.ps1"
}

& .\.venv\Scripts\Activate.ps1

$hostBind = if ($env:TAUROS_HOST) { $env:TAUROS_HOST } else { "127.0.0.1" }
$port = if ($env:TAUROS_PORT) { $env:TAUROS_PORT } else { "8000" }

Write-Host "TAUROS in ascolto su http://${hostBind}:${port}" -ForegroundColor Cyan
Write-Host "  App PWA  → http://${hostBind}:${port}/"
Write-Host "  Console  → http://${hostBind}:${port}/console"
Write-Host "  Health   → http://${hostBind}:${port}/health"
Write-Host "Ctrl+C per fermare."

uvicorn tauros.api:app --host $hostBind --port $port
