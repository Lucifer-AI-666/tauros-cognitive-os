# Install TAUROS as a dockerless always-on Windows task (boot + logon).
# Requires: existing .venv, gcloud ADC. Does not use Docker/Minikube.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Watchdog = Join-Path $Root "scripts\tauros_watchdog.ps1"
$TaskName = "TAUROS-AlwaysOn"
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) { throw "Venv assente. Esegui prima .\install.ps1" }
if (-not (Test-Path $Watchdog)) { throw "Manca $Watchdog" }

Write-Host "==> dipendenze vertex"
& $Python -m pip install -q "google-auth[requests]>=2.29,<3"

$arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Watchdog`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $Root
$startup = New-ScheduledTaskTrigger -AtStartup
$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($startup, $logon) `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "==> avvio task"
Start-ScheduledTask -TaskName $TaskName

$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) {
            Write-Host $r.Content
            $ok = $true
            break
        }
    } catch {}
}

if (-not $ok) {
    Write-Host "Task registrato ma health non ancora pronto. Log: $Root\logs\always-on.log"
    exit 1
}

Write-Host ""
Write-Host "TAUROS always-on attivo (senza Docker)."
Write-Host "  App     http://127.0.0.1:8000/"
Write-Host "  Console http://127.0.0.1:8000/console"
Write-Host "  Health  http://127.0.0.1:8000/health"
Write-Host "Disinstalla: .\scripts\uninstall_always_on.ps1"
