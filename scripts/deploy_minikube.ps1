# Build Tauros into Minikube and deploy with Vertex + gcp-auth.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

function Assert-Command($name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "Comando mancante: $name"
    }
}

Assert-Command minikube
Assert-Command kubectl
Assert-Command docker

Write-Host "==> cluster"
minikube status
if ($LASTEXITCODE -ne 0) {
    throw "Minikube non e' in esecuzione. Avvia con: minikube start --driver=docker"
}

$addon = minikube addons list | Select-String "gcp-auth"
if (-not ($addon -match "enabled")) {
    Write-Host "==> abilito gcp-auth"
    $env:GOOGLE_CLOUD_PROJECT = "dotted-lexicon-496211-k1"
    minikube addons enable gcp-auth
}

Write-Host "==> docker env minikube"
minikube -p minikube docker-env --shell powershell | Invoke-Expression

Write-Host "==> build immagine tauros-cognitive-os:local"
Set-Location $Root
docker build -t tauros-cognitive-os:local .
if ($LASTEXITCODE -ne 0) { throw "docker build fallito" }

$secretExists = kubectl get secret tauros-api -o name --ignore-not-found
if (-not $secretExists) {
    Write-Host "==> creo secret tauros-api"
    $token = python -c "import secrets; print(secrets.token_urlsafe(32))"
    if (-not $token) { throw "Impossibile generare il token API" }
    kubectl create secret generic tauros-api --from-literal=token=$token | Out-Null
} else {
    Write-Host "==> secret tauros-api gia' presente"
}

Write-Host "==> apply manifest"
kubectl apply -f (Join-Path $Root "k8s\deployment.yaml")
kubectl rollout restart deployment/tauros
kubectl rollout status deployment/tauros --timeout=180s

Write-Host "==> pod"
kubectl get pods -l app=tauros -o wide
kubectl get pod -l app=tauros -o jsonpath="{range .items[0].spec.containers[0].env[*]}{.name}{'\n'}{end}"
Write-Host ""
Write-Host "Deploy ok. Per la console locale:"
Write-Host "  kubectl port-forward svc/tauros 8000:8000"
Write-Host "Poi apri http://127.0.0.1:8000  (Bearer = contenuto del secret tauros-api)"
