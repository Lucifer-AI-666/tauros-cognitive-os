# One click: ensure TAUROS is up, then open the app already logged in.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Health = "http://127.0.0.1:8000/health"
$App = "http://127.0.0.1:8000/"

function Test-Up {
    try {
        $r = Invoke-WebRequest -Uri $Health -UseBasicParsing -TimeoutSec 2
        return $r.StatusCode -eq 200
    } catch { return $false }
}

if (-not (Test-Up)) {
    if (Get-ScheduledTask -TaskName "TAUROS-AlwaysOn" -ErrorAction SilentlyContinue) {
        Start-ScheduledTask -TaskName "TAUROS-AlwaysOn"
    } else {
        Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", (Join-Path $Root "scripts\tauros_watchdog.ps1")
        )
    }
    for ($i = 0; $i -lt 25; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Up) { break }
    }
}

if (-not (Test-Up)) {
    Start-Process notepad.exe (Join-Path $Root "logs\always-on.log")
    exit 1
}

Start-Process $App
