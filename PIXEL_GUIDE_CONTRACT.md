# Contratto TAUROS per la guida Pixel (DIB OS)

Uso: Kimi / `dibos-pixel-guide` documentano e avviano TAUROS.  
Il codice del cervello resta in `tauros-cognitive-os`. Non copiare `tauros/*.py` nella guida.

## Runtime

| Voce | Valore |
|------|--------|
| Bind | `127.0.0.1:8000` (LAN e public bind restano false) |
| App | `http://127.0.0.1:8000/` |
| Console | `http://127.0.0.1:8000/console` |
| Health | `GET /health` → `ok: true` |
| Token | solo `.env` locale (`tauros init`); mai in client, log, screenshot, git |
| Allowlist | un workspace (es. `~/DIBOSWorkspace`), nient’altro |
| Shell | `run_shell` non esiste e non va aggiunto |

## Avvio (Termux / Linux sul Pixel)

Stesso flusso già nella guida (`TaurosModule`): `install.sh` → `tauros init` → `tauros doctor` → `start.sh`.

Provider: Ollama locale primo; Groq/OpenAI-compatible solo come motore noleggiato. Chiavi solo server-side.

## Cosa la guida può fare

- Generare comandi e preview `.env` (senza token/API key).
- Checklist: doctor ok, `/health`, token non esposto, allowlist stretta, backup DB.

## Cosa la guida non fa

- Non flasha, non sblocca bootloader, non è il gate DIB OS.
- Non esegue tool CONTROLLED_ROOT.
- Non incolla eccezioni provider o corpi upstream nell’UI.

Versione nucleo: **0.4.5**.
