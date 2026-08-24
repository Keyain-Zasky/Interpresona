# Stato progetto Interpresona 2

## Completato

- Motore EXH/EXD unificato con compilazione e hard-inject SQPACK.
- Admin Studio locale con catalogo EXH, workspace, audit byte, backup e restore.
- Installer standalone senza dipendenze FastAPI/Uvicorn.
- Aggiornamento remoto con manifest, SHA-256, ZIP e comando `apply`.
- Portale remoto con manifest deduplicato, pubblicazione amministrativa e ticket.
- Console `/admin` per rispondere alle segnalazioni.
- Archivio dei diagnostici storici fuori dal progetto principale.

## Prossimi passi

- Sostituire i file dimostrativi del portale con bundle nominati secondo gli EXH
  canonici del workspace approvato.
- Aggiungere firma crittografica del manifest oltre allo SHA-256.
- Creare pacchetti eseguibili Windows/Linux/Steam Deck dell'installer.
- Aggiungere test automatici EXH/EXD e test di rollback su SQPACK duplicati.
