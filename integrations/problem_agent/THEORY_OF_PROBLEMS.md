# Theory of Problems (TAUROS)

Questo documento non spiega *come* funziona l’Agente del Problema.  
Spiega **che cos’è un “problema” per TAUROS**.

Senza questa teoria, il manifesto resta filosofia e lo schema output resta sintassi:  
manca il significato condiviso delle parole che l’agente usa.

---

## 1. Catena canonica

TAUROS distingue livelli che spesso vengono confusi in un’unica frase dell’utente.

```text
Richiesta
    ↓
Problema
    ↓
Obiettivo
    ↓
Vincoli
    ↓
Criteri di successo
    ↓
Soluzione
```

L’**Agente del Problema** opera **sopra** la riga della Soluzione.  
Non progetta la soluzione: rende espliciti e migliorabili i passi che la precedono.

---

## 2. Definizioni operative

### Richiesta
Ciò che l’utente *dice* (testo grezzo, desiderio, ordine, domanda).  
Può essere ambigua, incompleta o già precisa.  
È un **input linguistico**, non ancora un problema ben posto.

Esempio: *«Voglio mettere pannelli solari tra i binari».*

### Problema
Uno **scarto** tra uno stato attuale (implicito o dichiarato) e uno stato desiderato,  
in un contesto reale, con incertezza e possibili trade-off.  
Un problema ben posto risponde almeno a: *cosa non va / cosa manca / perché conta ora*.

Non è “la feature da implementare”. È la **tensione da risolvere**.

### Obiettivo
Il **risultato desiderato** formulato in modo orientato all’esito, non al mezzo.  
L’obiettivo *apparente* è ciò che la richiesta sembra chiedere.  
L’obiettivo *reale probabile* è ciò che, con le informazioni disponibili, sembra valere davvero  
(sempre come ipotesi, non come verità inventata).

### Vincoli
Limiti che **restringono** lo spazio delle soluzioni ammissibili:  
tecnici, legali, economici, temporali, di sicurezza, di manutenibilità, etici.  
I vincoli *mancanti* sono quelli che andrebbero noti prima di progettare, ma non lo sono ancora.

### Criteri di successo
Come si **sa** se una soluzione ha funzionato: metriche, soglie, test, osservabili.  
Senza criteri, ogni “soluzione” è opinione.

### Soluzione
Un piano, un design, un’azione o un sistema che mira a chiudere lo scarto  
**rispettando vincoli e criteri**.  
Appartiene ad altri agenti (Progettista, Ricercatore, …), non a questo modulo.

---

## 3. Cosa NON è un problema (per TAUROS)

| Non è un problema | Perché |
|-------------------|--------|
| Una soluzione mascherata da domanda | *«Usa PostgreSQL»* non espone lo scarto |
| Un desiderio senza contesto | Manca il “perché / dove / con quali limiti” |
| Un compito già completamente specificato | Può essere una **richiesta eseguibile** → spesso `PROCEED` |
| Un’ipotesi presentata come fatto | Va etichettata come assunzione, non come vincolo certo |

Il motore **non inventa** fatti per riempire i buchi: li segnala come assunzioni o vincoli mancanti  
(vedi `MANIFESTO.md`).

---

## 4. Assunzioni

Credenze **non verificate** su cui la richiesta poggia.  
Sono legittime come ipotesi di lavoro; diventano pericolose se trattate come vincoli certi.

L’agente deve:

1. renderle **visibili**;
2. non spacciarle per dati;
3. preferire riformulazioni che le riducono o le rendono testabili.

---

## 5. Relazione con le decisioni dell’agente

| Decisione | Significato nella teoria |
|-----------|---------------------------|
| **PROCEED** | La richiesta è già abbastanza vicina a un problema/obiettivo verificabile; si può scendere verso la soluzione. |
| **INTEGRATE** | Il problema è sensato, ma mancano vincoli o criteri essenziali: integrare informazioni prima di risolvere. |
| **REFRAME** | Una riformulazione migliora chiarezza, fattibilità, valore o verificabilità rispetto alla richiesta grezza. |

Le riformulazioni non sono “copy creativo”: sono **candidati di problema meglio posti**  
lungo la catena Richiesta → … → Criteri.

---

## 6. Qualità di un problema ben posto (dimensioni)

Allineate a `QualityScore` / `SPECIFICATION.md`:

| Dimensione | Domanda |
|------------|---------|
| **Clarity** | Si capisce lo scarto e l’obiettivo senza ambiguità critiche? |
| **Feasibility** | È realistico nello spazio dei vincoli noti? |
| **Value** | Vale la pena affrontarlo (impatto / priorità)? |
| **Verifiability** | Esistono criteri di successo osservabili? |

Un REFRAME “buono” alza queste dimensioni **senza** inventare dati mancanti.

---

## 7. Principio di non-anticipo

```text
❌  Richiesta → Soluzione
✅  Richiesta → (Problema, Obiettivo, Vincoli, Criteri) → Soluzione
```

Qualsiasi agente a valle (Critico, Ricercatore, Progettista, Archivista, Coordinatore)  
dovrebbe ricevere un **problema inquadrato**, non solo il testo grezzo dell’utente,  
salvo decisione esplicita `PROCEED`.

---

## 8. Livelli del sistema (collegamento “cervello” vs “organizzazione”)

| Livello | Domanda | Esempi |
|---------|---------|--------|
| **1 — Motore di inferenza** | Come si calcola / si genera? | micrograd, nanoGPT, Transformer, LLM API |
| **2 — Organizzazione del ragionamento** | Come si struttura il lavoro cognitivo? | Problem Agent, Critico, Ricercatore, Coordinatore |

Non sono binari opposti: sono **stackabili**.  
Il livello 2 può usare euristica, LLM o modello addestrato **senza** cambiare questa teoria  
né il contratto pubblico dell’agente (`ProblemAnalysis`).

---

## 9. Implicazioni per l’implementazione

- `engine.py` produce bozze di obiettivo, assunzioni, vincoli, riformulazioni **in termini di questa teoria**.
- `evaluator.py` sceglie se la richiesta grezza è già adeguata o se un candidato di problema è superiore.
- Un futuro adapter LLM deve **riempire lo stesso schema**, non “chiacchierare” fuori contratto.
- I test dovrebbero coprire non solo il caso felice (es. ferroviario), ma anche: richiesta già chiara, richiesta troppo corta, richiesta che è già una soluzione mascherata.

---

## 10. Una frase da fissare

> Per TAUROS, un **problema** è uno scarto verificabile tra stato attuale e obiettivo,  
> reso esplicito insieme a vincoli e criteri di successo —  
> **prima** che qualcuno abbia il diritto di vendere una soluzione.
