# Terze parti (dipendenze dirette)

TAUROS installa le seguenti librerie Python (versioni esatte al momento di `pip install`).

| Pacchetto | Uso | Licenza tipica |
|-----------|-----|----------------|
| FastAPI | API HTTP | MIT |
| Uvicorn | ASGI server | BSD-3-Clause |
| httpx | Client HTTP (provider LLM, Telegram) | BSD-3-Clause |
| Pydantic | Validazione modelli | MIT |
| pydantic-settings | Config da `.env` | MIT |
| python-multipart | Form/upload FastAPI | Apache-2.0 |
| google-auth | ADC / token Vertex AI | Apache-2.0 |
| pytest (dev) | Test | MIT |
| ruff (dev) | Linting | MIT |

Le dipendenze transitive (Starlette, anyio, h11, …) portano le proprie licenze.

Per un inventario completo dopo l’installazione:

```powershell
pip install pip-licenses
pip-licenses --format=markdown
```

Nessuna di queste librerie viene ridistribuita in forma binaria in questo archivio:
vengono scaricate da PyPI al momento dell’installazione.
