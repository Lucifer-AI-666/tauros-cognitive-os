# TAUROS × DIB-NCM — THE BEAST

## Contratto architetturale — 26 novembre 2026

TAUROS deve evolvere verso un'intelligenza artificiale locale il cui unico motore generativo sia DIB-NCM (Next-Concept Modeling), basato sul raffinamento iterativo di rappresentazioni latenti e sulla decodifica non autoregressiva.

- Nessun LLM autoregressivo, provider remoto o fallback LLM nel percorso di inferenza NCM.
- Riutilizzare implementazioni e pesi compatibili nel rispetto delle licenze e delle attribuzioni; verificare la provenienza del modello originale prima dell'integrazione.
- Conservare orchestrazione, memoria, strumenti, policy e audit di TAUROS, separandoli dal motore neurale.
- Dimostrare autonomia offline, correttezza, latenza e consumo di memoria con test riproducibili. Nessuna prestazione dichiarata senza evidenze.
- Preservare il codice esistente durante la migrazione; nessuna rimozione irreversibile senza autorizzazione.

**Stato:** contratto di progettazione. Il motore NCM autonomo non è ancora implementato né validato. La migrazione sarà completata soltanto dopo il superamento dei test di accettazione.

**Principio:** TAUROS è il corpo. DIB-NCM è il cervello.
