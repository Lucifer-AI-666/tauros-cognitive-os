# TAUROS — Visione di prodotto

### L'assistente AI personale che cresce insieme a te

Tauros non è un semplice chatbot. È un ecosistema progettato per diventare un assistente personale persistente: ricorda il contesto, può funzionare in locale o nel cloud, e adatta l'esperienza all'utilizzatore. Il controllo dei dati e dell'identità resta dell'utente.

---

## Filosofia

> L'intelligenza artificiale deve adattarsi alla persona, non il contrario.

Quattro idee fondamentali:

1. **Memoria personale persistente** — non una chat monouso.
2. **Esecuzione locale quando possibile** — cloud opzionale.
3. **Architettura modulare** — provider, tool, policy, memoria intercambiabili.
4. **Espansione senza riscrivere il nucleo** — versioni e migrazioni.

---

## Cosa c'è oggi (stato reale del codice)

Versione corrente del monorepo Cognitive OS: **v0.4.5**.

| Area | Stato |
|------|--------|
| Memoria FTS5 + candidate/active | Funzionante |
| Hardening (token, allowlist, policy, migrazioni) | Funzionante |
| Provider Ollama / Groq / OpenAI-compatible | Funzionante |
| Login utente + password | Funzionante (v0.3) |
| Memoria isolata per utente | Funzionante (v0.3) |
| Modalità Ospite (quota messaggi) | Funzionante (v0.3) |
| Chat product UI + login | Funzionante (v0.3) |
| Console operativa / PWA | Funzionante |
| Planner multi-step JSON + esecutore + policy per step | Funzionante |
| Planner LLM (JSON) + fallback regole | Funzionante (v0.4) |
| Tool workspace search + git read-only | Funzionante (v0.4) |
| Brief / open loops / decision journal | Funzionante (v0.4) |
| Privilegi a livelli + elevazione temporanea + trust zones | Funzionante (v0.3.2) — no god mode permanente |
| Telegram bot unificato | Funzionante (v0.4, `tauros telegram`) |
| Voce STT/TTS in browser | Funzionante (v0.4, Web Speech) |
| Elevazione privilegi dalla console | Funzionante (v0.4.1) |
| Scritture supervisionate (bozza → ok → backup → write → verify) | Funzionante (v0.4.1) |
| Catalogo Groq vivo + allowlist modelli | Funzionante (v0.4.5) |
| Brain switch serializzato | Funzionante (v0.4.5) |
| Audit hash-chain + /audit/verify | Funzionante (v0.4.5) |
| Retry HTTP + fallback Groq→Ollama | Funzionante (v0.4.5) |
| Plugin firmati / dichiarativi | Pianificato (v0.4.2) |
| APK Android | PWA installabile; APK nativo pianificato |
| Sync multi-dispositivo cloud | Pianificato |

---

## Architettura (nucleo)

```text
Utente
  │
Login / Guest / Operator token
  │
Memoria personale (user_id)
  │
Orchestrator
  ├── Planner
  ├── Policy + Path allowlist
  ├── Tools (read-only)
  └── Provider LLM (Ollama | Groq | OpenAI…)
  │
Risposta + traccia + audit
```

Il **modello propone**. La **policy decide**. L’**esecutore** agisce. L’**audit** registra.

---

## Ecosistema (direzione)

- Web App / PWA installabile
- Backend Cognitive OS (questo repo)
- Bot Telegram (stessa memoria utente)
- APK (stessa PWA o wrapper)
- Modelli locali + API cloud
- Voce, logging, aggiornamenti versionati

Obiettivo: **un’unica identità AI** su più dispositivi, con dati sotto il controllo dell’utente.

---

## Roadmap prodotto

### v1 — Assistente personale (in corso / nucleo pronto)

- [x] Chat + memoria
- [x] Ollama / cloud opzionale
- [x] Login multi-utente
- [x] Guest limitato
- [x] PWA
- [ ] APK packaging

### v2 — Voce e multi-canale

- TTS / STT
- Telegram sulla stessa auth/memoria
- UX mobile raffinata

### v3 — Locale pieno + agenti

- Planner multi-step con policy
- Plugin firmati
- Automazioni controllate

### v4 — Ecosistema distribuito

- Sync dispositivi
- Memoria condivisa opzionale
- Collaborazione tra agenti

---

## Principio non negoziabile

> TAUROS diventa più potente soltanto quando diventa anche più controllabile.

Niente modalità segreta. Niente god mode. Memorie candidate non sono verità finché l’utente non conferma.
