# Evaluation — valore reale dell’Agente del Problema

## Cosa *non* basta

Contare solo:

- quante volte esce `REFRAME`
- quante riformulazioni genera

misura **attività**, non **valore**.

## Metrica primaria (proposta v1)

> **Quanto migliora la qualità della risposta finale** quando lo stesso risolutore  
> riceve la domanda migliorata dall’agente invece della domanda grezza.

### Protocollo A/B

**Braccio A — baseline**

```text
Domanda originale
    → LLM (o altro solver), prompt fisso
    → Risposta A
    → Valutazione
```

**Braccio B — con Problem Agent**

```text
Domanda originale
    → Problem Agent
    → Domanda selezionata (o original se PROCEED)
    → stesso LLM, stesso prompt di sistema (salvo la domanda utente)
    → Risposta B
    → Valutazione
```

Condizioni di parità:

- stesso modello / temperatura / budget di token
- stesso giudice (umano e/o rubric automatica)
- stesso set di domande di test (benchmark fisso)

### Score di qualità della risposta (esempio di rubric 0–1)

| Criterio | Domanda al giudice |
|----------|-------------------|
| Correttezza / non allucinazione | Afferma solo ciò che si può sostenere? |
| Rispetto dei vincoli | Tiene conto di sicurezza, legge, costi se rilevanti? |
| Azionabilità | Si può eseguire o testare il passo successivo? |
| Completezza utile | Copre i pezzi critici senza riempitivo? |
| Allineamento all’obiettivo | Risponde all’obiettivo reale, non solo al mezzo? |

`delta = score(B) - score(A)`  
**Successo del modulo:** `mean(delta) > 0` in modo stabile sul benchmark.

### Metriche secondarie (utili ma non sufficienti)

| Metrica | Uso |
|---------|-----|
| Distribuzione PROCEED / INTEGRATE / REFRAME | Calibrazione del decisionore |
| Uplift medio di `QualityScore` (original → selected) | Coerenza interna agente |
| Tasso di assunzioni esplicitate | Trasparenza |
| Tempo / costo extra (chiamata agente + token) | ROI |

## Benchmark minimo (da costruire)

1. **10–30 richieste** reali o realistiche (IT/EN), eterogenee:
   - già chiare → atteso spesso PROCEED
   - ambigue → INTEGRATE / REFRAME
   - soluzione mascherata da richiesta
   - caso “pannelli/binari” (golden path euristico)
2. File versionato es. `benchmarks/cases.jsonl`
3. Script (futuro) `scripts/run_ab_eval.py` che produce tabella `delta` per caso

## Collegamento al contratto

L’eval **non** cambia `ProblemAnalysis`:  
usa `selected_question` (o equivalente) come input al solver a valle.  
Così euristica e futuro LLM adapter restano intercambiabili sotto la stessa misura.

## Principio

> L’Agente del Problema vale se fa **prendere decisioni migliori dopo**,  
> non se produce testo più lungo prima.
