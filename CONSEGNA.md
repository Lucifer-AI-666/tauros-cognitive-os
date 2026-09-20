# Consegna — TAUROS Cognitive OS v0.4.1

Pacchetto **completo e autonomo** in una sola cartella.

## Contenuto

| Percorso | Descrizione |
|----------|-------------|
| `tauros/` | Nucleo Python (API, memoria, policy, planner, scritture, Telegram) |
| `web/` | App prodotto + console + **PWA** (manifest, SW, icone, offline) |
| `config/system_prompt.md` | Identità di sistema |
| `tests/` | Suite pytest |
| `scripts/` | Utility (smoke Groq, tunnel, …) |
| `Dockerfile` + `docker-compose*.yml` + `Caddyfile` | Deploy locale / produzione HTTPS |
| `LICENSE` + `NOTICE` + `licenses/` | Licenza MIT e terze parti |
| `README.md` | Manuale avvio e uso |
| `VISION.md` | Visione prodotto e roadmap |
| `CHANGELOG.md` | Storia versioni |
| `.env.example` | Template configurazione (senza segreti) |
| `install.ps1` / `install.sh` | Installazione |
| `start.ps1` / `start.sh` | Avvio API |

## Non incluso (di proposito)

- `.env` con token/API key reali
- `.venv` (si crea con install)
- Database utente `data/tauros.db` (si crea al primo avvio)
- Log e backup personali

## Verifica rapida post-consegna

```powershell
cd TAUROS_Cognitive_OS_v0.4.1
.\install.ps1
.\.venv\Scripts\Activate.ps1
tauros init --owner "Tuo Nome" --allowlist "C:\path\workspace"
# aggiungi TAUROS_GROQ_API_KEY in .env se usi Groq
tauros doctor
pytest -q
.\start.ps1
```

Apri:

- App / PWA: http://127.0.0.1:8000/
- Console: http://127.0.0.1:8000/console

## Principio

> Il modello propone. La policy decide. L’esecutore agisce. L’audit registra.
