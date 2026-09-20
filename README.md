# TAUROS Cognitive OS v0.4.1

**Sistema Operativo Cognitivo Personale — local-first, hardened, multi-canale.**

Il modello linguistico è intercambiabile. Identità, memoria, strumenti, regole e audit appartengono a **TAUROS**.

> TAUROS diventa più potente soltanto quando diventa anche più controllabile.  
> Il modello propone. La policy decide. L’esecutore agisce. L’audit registra.

---

## Contenuto del pacchetto

| Elemento | Descrizione |
|----------|-------------|
| **App PWA** | Chat, login, ospite, installabile (`web/app.html` + manifest + SW) |
| **Console** | Overview, memoria, open loops, decisioni, brief, scritture, privilegi, audit |
| **API** | FastAPI su `127.0.0.1:8000` di default |
| **Planner** | Regole + LLM → JSON validato → policy per step |
| **Scritture 0.4.1** | Bozza → anteprima → conferma → backup → write → verify / rollback |
| **Telegram** | `tauros telegram` (opzionale) |
| **Voce** | STT/TTS nel browser (Web Speech) |
| **Docker / Caddy** | Deploy locale e produzione HTTPS |
| **Licenze** | `LICENSE` (MIT), `NOTICE`, `licenses/THIRD_PARTY.md` |

Vedi anche: [VISION.md](VISION.md) · [CHANGELOG.md](CHANGELOG.md) · [CONSEGNA.md](CONSEGNA.md)

---

## Requisiti

- **Python 3.11+** (testato anche su 3.14)
- Windows, macOS o Linux
- Opzionale: chiave **Groq** / **OpenAI**, o **Ollama** in locale
- Opzionale: Docker, bot token Telegram

---

## Avvio rapido (Windows)

```powershell
cd TAUROS_Cognitive_OS_v0.4.1
.\install.ps1
.\.venv\Scripts\Activate.ps1
tauros init --owner "IlTuoNome" --allowlist "C:\Users\TUO\TaurosWorkspace"
# Modifica .env: TAUROS_GROQ_API_KEY=...  e trust zones se serve
tauros doctor
.\start.ps1
```

## Avvio rapido (Linux / macOS)

```bash
cd TAUROS_Cognitive_OS_v0.4.1
chmod +x install.sh start.sh
./install.sh
source .venv/bin/activate
tauros init --owner "IlTuoNome" --allowlist "$HOME/TaurosWorkspace"
# edita .env
tauros doctor
./start.sh
```

### URL

| URL | Uso |
|-----|-----|
| http://127.0.0.1:8000/ | **App prodotto** (login / chat / PWA) |
| http://127.0.0.1:8000/console | **Console operativa** (token `TAUROS_API_TOKEN`) |
| http://127.0.0.1:8000/health | Health check JSON |

**Login app:** registrati, accedi, oppure **Ospite** (quota messaggi).  
**Console:** bearer token da `.env` (non la chiave Groq).

### PWA (installa come app)

- **Chrome / Edge** (localhost o HTTPS): menu → **Installa app** / icona installa in-app
- **iPhone:** Safari → Condividi → **Aggiungi a Home**
- Shell offline: `web/offline.html` + service worker `web/sw.js`
- Manifest: `web/manifest.webmanifest` · icone in `web/icons/`

---

## Privilegi (non god mode)

```text
BASE → OPERATOR → ADMINISTRATOR → CONTROLLED_ROOT
```

| Livello | Capacità tipiche |
|---------|------------------|
| BASE | Chat, lettura leggera |
| OPERATOR | Workspace search, git read-only, proposte scrittura |
| ADMINISTRATOR | Approvare scritture, backup, elevate ops |
| CONTROLLED_ROOT | Alto rischio, solo elevazione temporanea + conferma forte |

- Elevazione dalla **console → Sicurezza** (o `POST /privileges/elevate`)
- Frase forte predefinita: `CONFERMO ADMIN`
- Trust zones: `TAUROS_TRUST_ZONES` (meno frizione sulle approvazioni)

---

## Scritture supervisionate (v0.4.1)

```text
propose_write / propose_patch
  → anteprima console (prima / dopo / rischio)
  → elevazione se serve
  → approve (confirm + frase forte fuori trust zone)
  → snapshot file
  → scrittura
  → verifica hash
  → rollback se fallisce
  → audit
```

**Non inclusi di proposito (ancora):** delete libero, shell di sistema, install pacchetti OS.

Console: vista **Scritture** + **Sicurezza**.

---

## Planner multi-step

```text
Piano JSON (regole o LLM)
  → Validatore
  → Policy + PathGuard (ogni step)
  → Esecutore (uno step alla volta)
  → Audit
```

Se un passaggio è negato, il piano **si ferma**.  
Max step: `TAUROS_MAX_PLAN_STEPS` (default 3).

---

## Tool principali

| Tool | Tipo |
|------|------|
| `system_info`, `disk_usage` | Info |
| `list_directory`, `read_text_file` | FS read |
| `workspace_search`, `project_summary` | Ricerca / summary |
| `git_status`, `git_log`, `git_diff` | Git read-only |
| `memory_search` | Memoria |
| `propose_write`, `propose_patch`, `file_snapshot` | Bozze / rollback point |

---

## Provider LLM

```env
TAUROS_PROVIDER=groq          # ollama | groq | openai | openai-compatible | vertex
TAUROS_MODEL=openai/gpt-oss-20b
TAUROS_GROQ_API_KEY=...
# oppure
TAUROS_PROVIDER=ollama
TAUROS_MODEL=llama3.2:3b
TAUROS_OLLAMA_URL=http://127.0.0.1:11434
# Vertex AI Gemini — usa ADC (gcloud auth application-default login)
# o l'addon minikube gcp-auth, nessuna API key
TAUROS_PROVIDER=vertex
TAUROS_MODEL=gemini-2.5-flash
TAUROS_VERTEX_PROJECT=dotted-lexicon-496211-k1
TAUROS_VERTEX_LOCATION=europe-west1
```

Su Minikube, dopo `minikube addons enable gcp-auth`:

```powershell
.\scripts\deploy_minikube.ps1
```

Always-on **senza Docker** (processo Windows al boot/login, Vertex via ADC):

```powershell
.\scripts\install_always_on.ps1
```

---

## Telegram (opzionale)

```env
TAUROS_TELEGRAM_BOT_TOKEN=123456:ABC...
```

```powershell
tauros telegram
```

Comandi bot: `/start`, `/link <token_sessione>`, `/brief`, messaggi → chat con memoria.

---

## CLI

```text
tauros init | doctor | status | migrate | backup | restore
tauros chat | memories | remember "..." | brief | telegram
```

---

## Test

```powershell
.\.venv\Scripts\Activate.ps1
pytest -q
```

---

## Docker (produzione HTTPS)

```bash
export DOMAIN=tauros.example.com
# .env con token forte, chiavi, allowlist, ALLOW_PUBLIC_BIND
docker compose -f docker-compose.prod.yml up -d --build
```

Vedi `Caddyfile` e `docker-compose.prod.yml`.

---

## Sicurezza di default

- Bind `127.0.0.1`
- Token API forte obbligatorio
- Allowlist filesystem
- Modalità `read_only` (scritture solo supervisionate + elevazione)
- Redazione segreti in log/audit
- Migrazioni versionate con backup

---

## Licenza

MIT — vedi [LICENSE](LICENSE) e [NOTICE](NOTICE).  
Dipendenze: [licenses/THIRD_PARTY.md](licenses/THIRD_PARTY.md).

---

## Struttura cartelle

```text
TAUROS_Cognitive_OS_v0.4.1/
├── LICENSE, NOTICE, README.md, VISION.md, CHANGELOG.md, CONSEGNA.md
├── licenses/THIRD_PARTY.md
├── pyproject.toml
├── .env.example
├── install.ps1 / install.sh
├── start.ps1 / start.sh
├── Dockerfile, docker-compose.yml, docker-compose.prod.yml, Caddyfile
├── config/system_prompt.md
├── tauros/          # motore
├── web/             # PWA + console
│   ├── app.html, index.html, sw.js, manifest.webmanifest, offline.html
│   └── icons/
├── tests/
├── scripts/
└── data/            # creato a runtime (db, backup)
```

---

## Roadmap sintetica

| Versione | Focus |
|----------|--------|
| 0.4.0 | Continuità, tool, planner LLM, Telegram, voce |
| **0.4.1** | **Elevazione UI + scritture supervisionate** |
| 0.4.2 | Plugin firmati e dichiarativi |
| 0.5+ | Sync multi-dispositivo, più azioni ad alto rischio controllate |
