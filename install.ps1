# TAUROS Cognitive OS — installazione Windows
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== TAUROS install ===" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Error "Python non trovato. Installa Python 3.11+ da https://www.python.org/"
}

python -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"

New-Item -ItemType Directory -Force -Path data, logs | Out-Null
if (-not (Test-Path .env)) {
  Copy-Item .env.example .env
  Write-Host "Creato .env da .env.example" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Installazione OK." -ForegroundColor Green
Write-Host "Prossimi passi:"
Write-Host "  1. .\.venv\Scripts\Activate.ps1"
Write-Host "  2. tauros init --owner `"IlTuoNome`" --allowlist `"C:\path\workspace`""
Write-Host "  3. Modifica .env (es. TAUROS_GROQ_API_KEY)"
Write-Host "  4. tauros doctor"
Write-Host "  5. .\start.ps1"
Write-Host "  App:     http://127.0.0.1:8000/"
Write-Host "  Console: http://127.0.0.1:8000/console"
