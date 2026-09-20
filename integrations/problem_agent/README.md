# TAUROS Problem Agent

> Nessun agente dovrebbe risolvere un problema prima che qualcuno abbia verificato che sia il problema giusto.

Questo repository contiene il prototipo completo dell'Agente del Problema di TAUROS.

## Funzioni

1. Identifica l'obiettivo reale.
2. Separa richiesta, bisogno, assunzioni e vincoli.
3. Genera fino a tre riformulazioni.
4. Decide tra `PROCEED`, `INTEGRATE` e `REFRAME`.

## Installazione

```bash
python -m venv .venv
pip install -e ".[dev]"
pytest
```

## Uso

```bash
tauros-problem "Voglio mettere pannelli solari tra i binari"
```

Output JSON:

```bash
tauros-problem --json "Voglio mettere pannelli solari tra i binari"
```

## API opzionale

```bash
pip install -e ".[api]"
uvicorn tauros_problem_agent.api:app --reload
```

## Documenti fondativi

| Documento | Ruolo |
|-----------|--------|
| [MANIFESTO.md](MANIFESTO.md) | Identità, missione, limiti |
| [THEORY_OF_PROBLEMS.md](THEORY_OF_PROBLEMS.md) | Che cos’è un *problema* per TAUROS |
| [SPECIFICATION.md](SPECIFICATION.md) | Contratto: decisioni e schema output |
| [EVALUATION.md](EVALUATION.md) | Come misurare se l’agente crea valore reale |

## Struttura

```text
Utente -> Agente del Problema -> Coordinatore -> Risposta
```

```text
Richiesta → Problema → Obiettivo → Vincoli → Criteri di successo → Soluzione
            ^—— questo modulo lavora qui ——^
```

Il prototipo usa un motore euristico locale, trasparente e senza API esterne. In seguito potrà essere sostituito da un adapter LLM senza cambiare il contratto pubblico.

**Roadmap disciplinata:** non aggiungere altri agenti (Critico, Ricercatore, …) finché non si misura, con il protocollo in `EVALUATION.md`, se questo modulo migliora la qualità delle risposte a valle.
