# Changelog

## 0.4.5 — 2026-09-20

Catalogo Groq vivo, allowlist modelli, lock su PUT /brain, hash-chain audit,
retry HTTP su tutti i provider HTTP, fallback Groq→Ollama, console verifica catena.

## 0.4.4 — 2026-09-06 (seguito 2026-09-20)

### Retry / fallback
- Retry HTTP (3 tentativi) su Groq/OpenAI-compatible, Ollama e Vertex (non più solo Vertex).
- Groq ha fallback Ollama locale (`llama3.2:3b`) se `TAUROS_OLLAMA_URL` è impostato. Non si usa DIB `:1988` (loop).

### Audit hash-chain
- Ogni riga audit ha `prev_hash` + `row_hash` SHA-256. `GET /audit/verify` (operator) segnala tagli o modifiche.

### Brain switch
- `BrainRuntime.apply` serializza PUT concorrenti (lock): orchestrator, planner e `brain.json` restano allineati.

### Allowlist modelli
- `PUT /brain` per groq, vertex, openai accetta solo id del catalogo.
- I nomi Groq ritirati (`llama-3.3-70b-versatile`, ecc.) tornano 400.

### Catalogo Groq
- I modelli Llama 3.3 / 3.1 / Gemma 2 su Groq non esistono più su questa chiave (HTTP 404).
- Default e catalogo: `openai/gpt-oss-20b`, `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`, `groq/compound`.
- Non usare `dib` come provider Tauros se DIB Brain (`:1988`) a sua volta chiama Tauros: loop.

## 0.4.4 — 2026-09-06

### Hardening risposte degrade
- La risposta degradata non espone più il dettaglio provider (`{exc}`):
  errore redatto in audit come `provider_error`, l'utente riceve un `error_ref` di correlazione
- Canale Telegram: eccezioni di chat non includono più `{exc}` nel messaggio utente; solo `error_ref`
- `pyproject.toml` allineato a `tauros/__init__.py`

## 0.4.3 — 2026-08-13

### Agent Layer — Finestra Regole
- Base regole utente (`data/rules.json`) consultata dal PolicyEngine prima di ogni tool
- `deny` utente vince sempre; API `/rules` e `/agents`
- Console: vista **Regole**

## 0.4.2 — 2026-08-12

### Vertex AI + Minikube
- Provider `vertex` (Gemini su Vertex AI) con Application Default Credentials
- Niente API key: usa `GOOGLE_CLOUD_PROJECT` / ADC, incluso addon minikube `gcp-auth`
- Manifest Kubernetes e script `scripts/deploy_minikube.ps1`

## 0.4.1 — 2026-07-20

### Scritture supervisionate + elevazione UI
- Elevazione privilegi temporanea dalla console (livello, minuti, scope, singola operazione)
- Flusso bozza → anteprima → conferma → backup → scrittura → verifica hash → rollback
- Tool `propose_write`, `propose_patch`, `file_snapshot` (mai write diretto dal planner)
- API `/writes/*` e `/privileges/*`
- Console: viste Sicurezza e Scritture

## 0.4.0 — 2026-07-20

### Continuità e presenza
- Planner ibrido regole + LLM StructuredPlan
- Tool read-only: workspace search, git status/log/diff, project summary
- Brief, open loops, decision journal, consolidate memoria
- Stream chat, STT/TTS browser, bot Telegram
- PWA installabile (manifest + service worker)

## 0.3.x

- Multi-utente, guest, memoria isolata
- Planner multi-step sola lettura
- Privilegi BASE → CONTROLLED_ROOT, trust zones
- Hardening token, allowlist, migrazioni, audit

## 0.2.x

- Hardening filesystem, redazione segreti, CLI init/doctor/backup
