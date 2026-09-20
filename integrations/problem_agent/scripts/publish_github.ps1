<#
.SYNOPSIS
  Pubblica TAUROS Problem Agent su GitHub (account gh attivo).

.DESCRIPTION
  - Opzione A: aggiorna la repo esistente Lucifer-AI-666/TaurosAgenteDelProblema
  - Opzione B: crea una repo nuova (default: tauros-problem-agent)

  NON esegue push force. Chiede conferma se remote già presente.

.EXAMPLE
  # Aggiorna repo già creata (solo README oggi)
  .\scripts\publish_github.ps1 -Repo TaurosAgenteDelProblema -Visibility public

  # Crea repo nuova
  .\scripts\publish_github.ps1 -Repo tauros-problem-agent -Visibility public -Create
#>

param(
    [string]$Owner = "Lucifer-AI-666",
    [string]$Repo = "TaurosAgenteDelProblema",
    [ValidateSet("public", "private")]
    [string]$Visibility = "public",
    [switch]$Create,
    [switch]$SkipTests,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "== TAUROS Problem Agent — publish ==" -ForegroundColor Cyan
Write-Host "Root: $Root"
Write-Host "Target: https://github.com/$Owner/$Repo ($Visibility)"

# 1) auth
gh auth status | Out-Host

# 2) tests
if (-not $SkipTests) {
    Write-Host "`n[tests] pytest..." -ForegroundColor Yellow
    if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
        py -3.12 -m venv .venv
        .\.venv\Scripts\python.exe -m pip install -U pip
        .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
    }
    .\.venv\Scripts\python.exe -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "pytest failed — abort publish" }
}

# 3) git init se serve
if (-not (Test-Path .git)) {
    git init
    git branch -M main
}

# 4) evita di committare venv/cache
if (-not (Test-Path .gitignore)) {
    @"
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.ruff_cache/
dist/
build/
*.egg-info/
.env
"@ | Set-Content .gitignore -Encoding utf8
}

git add -A
$status = git status --porcelain
if ($status) {
    git commit -m "feat: TAUROS Problem Agent prototype (heuristic engine, CLI, tests)"
} else {
    Write-Host "Niente da committare (working tree clean)." -ForegroundColor DarkGray
}

$remoteUrl = "https://github.com/$Owner/$Repo.git"

# 5) create repo se richiesto
$exists = $true
gh repo view "$Owner/$Repo" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { $exists = $false }

if (-not $exists) {
    if (-not $Create) {
        throw "Repo $Owner/$Repo non esiste. Rilancia con -Create oppure scegli un nome esistente."
    }
    Write-Host "`n[create] gh repo create $Owner/$Repo ..." -ForegroundColor Yellow
    if ($Visibility -eq "public") {
        gh repo create "$Owner/$Repo" --public --source=. --remote=origin --description "TAUROS Problem Agent — verifica il problema prima della soluzione"
    } else {
        gh repo create "$Owner/$Repo" --private --source=. --remote=origin --description "TAUROS Problem Agent — verifica il problema prima della soluzione"
    }
} else {
    Write-Host "`n[remote] repo esiste già — imposto origin e push" -ForegroundColor Yellow
    $hasOrigin = git remote get-url origin 2>$null
    if (-not $hasOrigin) {
        git remote add origin $remoteUrl
    } else {
        git remote set-url origin $remoteUrl
    }
}

if (-not $Yes) {
    $ans = Read-Host "Push su $remoteUrl (main)? [y/N]"
    if ($ans -notmatch '^[yY]') { Write-Host "Annullato."; exit 0 }
}

git push -u origin main
Write-Host "`nOK → https://github.com/$Owner/$Repo" -ForegroundColor Green
Write-Host "Clone:  git clone $remoteUrl"
Write-Host "CLI:    pip install -e .  &&  tauros-problem `"Voglio mettere pannelli solari tra i binari`""
