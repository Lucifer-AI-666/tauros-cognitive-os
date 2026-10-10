# Incarico di revisione per GitHub Copilot

Rivedi il diff della PR rispetto alla base, senza modificare main o indebolire i test.

1. Verifica il percorso installer → template .env → tauros init: token vuoto/debole, token forte esistente, rotazione, preservazione dell’allowlist e delle impostazioni personalizzate.
2. Controlla l’impatto dei default OTP debug e local-click login disabilitati. Cerca regressioni o bypass nei flussi API e nelle configurazioni proxy.
3. Verifica CORS PUT per /brain e /rules e adeguatezza del test preflight.
4. Confronta README con codice, CLI e packaging. Segnala istruzioni non riproducibili o promesse non dimostrate.
5. Valuta i test aggiunti per capacità di rilevare regressioni reali.

Riporta problemi con file, comportamento osservato, gravità e proposta motivata. Distingui difetti introdotti, problemi preesistenti e miglioramenti opzionali. Non considerare come verifica live le informazioni storiche TAUROS_*.txt.
