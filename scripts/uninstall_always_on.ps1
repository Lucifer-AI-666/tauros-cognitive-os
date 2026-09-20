# Stop and remove the TAUROS always-on task.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$TaskName = "TAUROS-AlwaysOn"
$PidFile = Join-Path $Root "data\tauros.pid"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Task $TaskName rimosso"
} else {
    Write-Host "Task $TaskName non presente"
}

if (Test-Path $PidFile) {
    $id = 0
    if ([int]::TryParse((Get-Content $PidFile | Select-Object -First 1), [ref]$id) -and $id -gt 0) {
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -match "uvicorn tauros.api:app" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Host "Always-on fermato"
