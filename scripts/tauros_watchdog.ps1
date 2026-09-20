# TAUROS always-on watchdog — no Docker, no Minikube.
# Keeps uvicorn alive on 127.0.0.1:8000 using Vertex ADC.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
$LogDir = Join-Path $Root "logs"
$Log = Join-Path $LogDir "always-on.log"
$PidFile = Join-Path $Root "data\tauros.pid"
New-Item -ItemType Directory -Force -Path $LogDir, (Join-Path $Root "data") | Out-Null

function Write-Log([string]$msg) {
    $line = "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $msg
    Add-Content -Path $Log -Value $line -Encoding utf8
}

function Test-Health {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 3
        return ($r.StatusCode -eq 200 -and $r.Content -match '"ok":\s*true')
    } catch {
        return $false
    }
}

function Get-ChildPid {
    if (Test-Path $PidFile) {
        $raw = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
        $id = 0
        if ([int]::TryParse($raw, [ref]$id) -and $id -gt 0) {
            $p = Get-Process -Id $id -ErrorAction SilentlyContinue
            if ($p) { return $p }
        }
    }
    return $null
}

if (-not (Test-Path $Python)) {
    Write-Log "FAIL venv python assente: $Python"
    exit 2
}

$env:TAUROS_PROVIDER = "vertex"
$env:TAUROS_MODEL = "gemini-2.5-flash"
$env:TAUROS_VERTEX_LOCATION = "europe-west1"
$env:TAUROS_VERTEX_PROJECT = "dotted-lexicon-496211-k1"
$env:GOOGLE_CLOUD_PROJECT = "dotted-lexicon-496211-k1"
$env:GOOGLE_CLOUD_QUOTA_PROJECT = "dotted-lexicon-496211-k1"
$env:TAUROS_HOST = "127.0.0.1"
$env:TAUROS_PORT = "8000"

Write-Log "watchdog start provider=vertex model=gemini-2.5-flash"

while ($true) {
    if (Test-Health) {
        Start-Sleep -Seconds 15
        continue
    }

    $portTaken = $false
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect("127.0.0.1", 8000)
        $tcp.Close()
        $portTaken = $true
    } catch { $portTaken = $false }
    if ($portTaken) {
        Write-Log "porta 8000 occupata, non avvio un secondo uvicorn"
        Start-Sleep -Seconds 8
        continue
    }

    $existing = Get-ChildPid
    if ($existing) {
        Write-Log "health down, fermo pid=$($existing.Id)"
        try { Stop-Process -Id $existing.Id -Force -ErrorAction SilentlyContinue } catch {}
        Start-Sleep -Seconds 2
    }

    Write-Log "avvio uvicorn"
    $proc = Start-Process -FilePath $Python -ArgumentList @(
        "-m", "uvicorn", "tauros.api:app",
        "--host", "127.0.0.1",
        "--port", "8000",
        "--log-level", "info"
    ) -WorkingDirectory $Root -WindowStyle Hidden -PassThru
    Set-Content -Path $PidFile -Value $proc.Id -Encoding ascii

    $up = $false
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Health) { $up = $true; break }
        if ($proc.HasExited) { break }
    }
    if ($up) {
        Write-Log "ready pid=$($proc.Id) http://127.0.0.1:8000"
    } else {
        Write-Log "uvicorn non risponde (exited=$($proc.HasExited))"
        Start-Sleep -Seconds 8
    }
}
