# Avvio unico: Cognitive OS 0.4.4 su :8000, attesa /health, COSMOS se USB D: presente.
# Non lancia DIB AOSP, backup PERICOLOSO, ne run_shell.
$ErrorActionPreference = "Continue"
$CoreRoot = Split-Path -Parent $PSScriptRoot
$Health = "http://127.0.0.1:8000/health"
$App = "http://127.0.0.1:8000/"
$Console = "http://127.0.0.1:8000/console"
$Python = Join-Path $CoreRoot ".venv\Scripts\python.exe"
$NexusRoot = "C:\Users\anouar\divine-nexus"
$NexusHealth = "http://127.0.0.1:3000/api/health"
$NexusUi = "http://127.0.0.1:8081"
$CosmosCandidates = @(
    "C:\Users\anouar\cosmos_rmm_project",
    "D:\uno\cosmos_rmm_project-1\cosmos_rmm_project",
    "D:\uno\cosmos_rmm_project"
)

function Test-Url([string]$Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Test-Up { return Test-Url $Health }

Write-Host "=== DIB / TAUROS launcher ===" -ForegroundColor Cyan
Write-Host "Core: $CoreRoot"

if (-not (Test-Path $Python)) {
    Write-Error "Venv assente. Esegui prima install.ps1 in $CoreRoot"
    exit 1
}

if (-not (Test-Up)) {
    Write-Host "Avvio uvicorn tauros.api:app su 127.0.0.1:8000 ..."
    $logDir = Join-Path $CoreRoot "logs"
    if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
    $outLog = Join-Path $logDir "uvicorn.log"
    $errLog = Join-Path $logDir "uvicorn.log.err"
    Start-Process -FilePath $Python -WorkingDirectory $CoreRoot -WindowStyle Minimized -ArgumentList @(
        "-m", "uvicorn", "tauros.api:app",
        "--host", "127.0.0.1", "--port", "8000", "--log-level", "info"
    ) -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    $ok = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Up) { $ok = $true; break }
        Write-Host "." -NoNewline
    }
    Write-Host ""
    if (-not $ok) {
        Write-Host "Health non risponde. Vedi $errLog" -ForegroundColor Red
        if (Test-Path $errLog) { Get-Content $errLog -Tail 30 }
        exit 1
    }
} else {
    Write-Host "Core gia in ascolto." -ForegroundColor Green
}

try {
    $h = Invoke-RestMethod -Uri $Health -TimeoutSec 5
    Write-Host ("Health OK  version={0}  provider={1}  ok={2}" -f $h.version, $h.provider, $h.ok)
} catch {
    Write-Host "Health HTTP 200 ma JSON non letto."
}

Start-Process $App
Write-Host "Aperto $App  (console: $Console)"

$envFile = Join-Path $CoreRoot ".env"
if (Test-Path $envFile) {
    $tokLine = Get-Content $envFile | Where-Object { $_ -match '^TAUROS_API_TOKEN=' } | Select-Object -First 1
    if ($tokLine) {
        $env:TAUROS_API_TOKEN = $tokLine.Substring("TAUROS_API_TOKEN=".Length).Trim().Trim('"').Trim("'")
    }
}
$env:TAUROS_BASE_URL = "http://127.0.0.1:8000"
$env:PORT = "3000"
$env:EXPO_NO_TELEMETRY = "1"

$logDir = Join-Path $CoreRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

function Start-CmdLogged([string]$WorkDir, [string]$CmdLine, [string]$OutLog, [string]$ErrLog) {
    $bat = Join-Path $logDir ("_run_" + [guid]::NewGuid().ToString("n").Substring(0,8) + ".cmd")
    @(
        "@echo off",
        "cd /d `"$WorkDir`"",
        "$CmdLine > `"$OutLog`" 2> `"$ErrLog`""
    ) | Set-Content -Path $bat -Encoding ASCII
    Start-Process -FilePath $bat -WindowStyle Minimized
}

if (Test-Path (Join-Path $NexusRoot "package.json")) {
    if (-not (Test-Url $NexusHealth)) {
        Write-Host "Avvio Nexus tRPC su :3000 ..."
        Start-CmdLogged $NexusRoot "pnpm.cmd dev:server" (Join-Path $logDir "nexus-api.log") (Join-Path $logDir "nexus-api.log.err")
        for ($i = 0; $i -lt 25; $i++) {
            Start-Sleep -Seconds 1
            if (Test-Url $NexusHealth) { break }
        }
    }
    if (Test-Url $NexusHealth) { Write-Host "Nexus API ok $NexusHealth" -ForegroundColor Green }
    else { Write-Host "Nexus API non risponde (vedi logs\nexus-api.log.err)" -ForegroundColor Yellow }

    if (-not (Test-Url $NexusUi)) {
        Write-Host "Avvio Nexus Expo web su :8081 ..."
        Start-CmdLogged $NexusRoot "npx.cmd expo start --web --port 8081" (Join-Path $logDir "nexus-ui.log") (Join-Path $logDir "nexus-ui.log.err")
        for ($i = 0; $i -lt 40; $i++) {
            Start-Sleep -Seconds 1
            if (Test-Url $NexusUi) { break }
        }
    }
    if (Test-Url $NexusUi) {
        Write-Host "Nexus UI ok $NexusUi" -ForegroundColor Green
        Start-Process $NexusUi
    } else {
        Write-Host "Nexus UI non risponde (vedi logs\nexus-ui.log.err)" -ForegroundColor Yellow
    }
} else {
    Write-Host "Nexus assente in $NexusRoot - skip."
}

$cosmos = $CosmosCandidates | Where-Object { Test-Path (Join-Path $_ "main.py") } | Select-Object -First 1
if ($cosmos) {
    $cosmosPy = Join-Path $cosmos ".venv\Scripts\python.exe"
    Write-Host "COSMOS RMM trovato: $cosmos"
    Write-Host "Non avviato in automatico (7 agenti, costa token Groq). Esempio:"
    if (Test-Path $cosmosPy) {
        Write-Host ('  & "' + $cosmosPy + '" "' + (Join-Path $cosmos "main.py") + '" --mission "missione breve"')
    } else {
        Write-Host ('  cd "' + $cosmos + '"; python main.py --mission "missione"')
    }
    $lastReport = Get-ChildItem (Join-Path $cosmos "outputs") -Directory -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($lastReport) {
        $md = Join-Path $lastReport.FullName "FINAL_REPORT.md"
        if (Test-Path $md) {
            Write-Host "Ultimo report: $md"
            Start-Process $md
        }
    }
} else {
    Write-Host "COSMOS: cartella assente - skip."
}

$tgOn = $false
$tgTok = $false
if (Test-Path $envFile) {
    $enLine = Get-Content $envFile | Where-Object { $_ -match '^TAUROS_TELEGRAM_ENABLED=' } | Select-Object -First 1
    if ($enLine -match '=true$|=1$|=yes$') { $tgOn = $true }
    $tgLine = Get-Content $envFile | Where-Object { $_ -match '^TAUROS_TELEGRAM_BOT_TOKEN=' } | Select-Object -First 1
    if ($tgLine -and $tgLine.Length -gt 'TAUROS_TELEGRAM_BOT_TOKEN='.Length + 8) { $tgTok = $true }
}
if ($tgOn -and $tgTok) {
    Write-Host "Telegram: token presente. Avvio: .\.venv\Scripts\python.exe -m tauros.cli telegram"
} else {
    Write-Host "Telegram: spento (TAUROS_TELEGRAM_ENABLED=false o token vuoto)."
}

Write-Host "Fatto. Core resta in esecuzione."
