# Legacy one-liner. Prefer: .\scripts\publish_github.ps1
param([Parameter(Mandatory=$true)][string]$RepositoryUrl)
$ErrorActionPreference="Stop"
git init
git branch -M main
git add .
git commit -m "feat: initial TAUROS Problem Agent prototype"
git remote add origin $RepositoryUrl
git push -u origin main
