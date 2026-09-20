# Keeps Ollama + DIB Brain (port 1988) alive.
$ErrorActionPreference = "Continue"
$DibDir = "C:\Users\anouar\esp32-ai-robot"
$Python = "C:\Python314\python.exe"
$OllamaApp = "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
$LogDir = Join-Path (Split-Path $PSScriptRoot) "logs"
$Log = Join-Path $LogDir "dib-always-on.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log([string]$msg) {
    $line = "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $msg
    Add-Content -Path $Log -Value $line -Encoding utf8
}

function Test-Port([int]$port) {
    try {
        $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        return [bool]$c
    } catch { return $false }
}

Write-Log "dib watchdog start"

while ($true) {
    if (-not (Test-Port 11434)) {
        Write-Log "ollama down, avvio app"
        if (Test-Path $OllamaApp) {
            Start-Process -FilePath $OllamaApp -WindowStyle Hidden
        } else {
            Start-Process -FilePath "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" -ArgumentList "serve" -WindowStyle Hidden
        }
        Start-Sleep -Seconds 4
    }

    if (-not (Test-Port 1988)) {
        Write-Log "dib brain down, avvio"
        Start-Process -FilePath $Python -ArgumentList "DIB_BRAIN_SERVER.py" -WorkingDirectory $DibDir -WindowStyle Hidden
        Start-Sleep -Seconds 3
    }

    Start-Sleep -Seconds 10
}
