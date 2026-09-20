# TAUROS Cognitive OS — Progetto completo (assemblato)

**Percorso canonico:** `C:\Users\anouar\tauros-cognitive-os`  
**Versione core:** 0.4.1  
**Assemblato da:** audit PC (luglio 2026)

---

## Da dove viene

| Parte | Fonte originale |
|-------|-----------------|
| Core Cognitive OS 0.4.1 | `Downloads\TAUROS_Cognitive_OS_v0.1\TAUROS_Cognitive_OS_v0.4.1\` |
| Problem Agent | `tauros-problem-agent\` → `integrations/problem_agent\` |
| Bridge API/orchestrator | aggiunto in `tauros/problem_bridge.py` + `/problem/*` |

Questa cartella è la **source of truth** del sistema cognitivo.  
Le altre copie in Downloads/Desktop restano archivio.

---

## Cosa include (completo)

| Componente | Path / endpoint |
|------------|-----------------|
| Package Python | `tauros/` (API, planner, policy, privileges, memory, tools, writes…) |
| App PWA | `web/app.html` → `/` |
| Console | `web/index.html` → `/console` |
| Config prompt | `config/system_prompt.md` |
| Test sicurezza/core | `tests/` (11 file) |
| Problem Agent | `integrations/problem_agent/` |
| API chat | `POST /chat` |
| API problem | `POST /problem/analyze`, `GET /problem/status` |
| CLI | `tauros` (init, doctor, telegram…) |
| Docker / Caddy | `Dockerfile`, `docker-compose*.yml`, `Caddyfile` |
| Install Windows | `install.ps1` → `start.ps1` |

**Principio:** *Il modello propone. La policy decide. L'esecutore agisce. L'audit registra.*

---

## Avvio (Windows)

```powershell
cd C:\Users\anouar\tauros-cognitive-os
.\install.ps1
.\.venv\Scripts\Activate.ps1
tauros init --owner "Anouar" --allowlist "C:\Users\anouar"
# modifica .env: TAUROS_GROQ_API_KEY=gsk_...  (o Ollama)
tauros doctor
.\start.ps1
```

Apri:

- App: http://127.0.0.1:8000/
- Console: http://127.0.0.1:8000/console
- Health: http://127.0.0.1:8000/health

### Test

```powershell
pytest -q
```

### Problem Agent (esempio)

```http
POST /problem/analyze
Authorization: Bearer <TAUROS_API_TOKEN>
Content-Type: application/json

{"message": "Voglio mettere pannelli solari tra i binari"}
```

In chat, se la decisione è REFRAME/INTEGRATE, un hint viene iniettato nel contesto del modello (audit: `problem_agent_hint`).

---

## Architettura

```text
Browser PWA / Console
        │
        ▼
   FastAPI (tauros.api)
        │
        ├─ Auth / privilegi / guest
        ├─ POST /problem/analyze  → Problem Agent
        └─ POST /chat
                │
                ▼
         Orchestrator
           ├─ Problem Agent hint (opz.)
           ├─ Memory recall
           ├─ Planner (rules + LLM)
           ├─ Policy + PlanExecutor
           ├─ Tools (allowlist paths)
           └─ LLM provider (Groq / Ollama / OpenAI)
                │
                ▼
         SQLite data/tauros.db + audit
```

---

## Cosa non è incluso qui (scelta consapevole)

| Fuori da questo repo | Perché |
|----------------------|--------|
| Hub UI Manus (oracolum-tauros-unified) | Front secondario; core è questa API + web/ |
| DIB-OS AOSP / dibctl | Progetto hardware Pixel separato |
| grok-esp32-s3 | Edge client; può parlare a questa API in futuro |
| NEXUS Telegram monolite | Runtime storico; operator pattern già in policy qui |
| nanoGPT / studio ML | Formazione, non runtime cognitivo |

---

## Sicurezza

- Non committare `.env`
- Token API forte (generato da `tauros init`)
- Default bind `127.0.0.1`
- `TAUROS_SECURITY_MODE=read_only` o `supervised` in uso quotidiano

---

## Manutenzione

- Aggiorna solo **questa** cartella.
- Archivio Downloads: non modificare come “prod”.
- Edge (ESP32): punta a `TAUROS_PUBLIC_BASE_URL` solo se esponi dietro HTTPS.
