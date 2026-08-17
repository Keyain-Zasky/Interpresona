# Interpresona — FFXIV Zero-Error Translator 2.0

Webapp locale per estrarre, tradurre, compilare e iniettare dati testuali di Final Fantasy XIV direttamente negli archivi SQPACK.

## Perché la 2.0

La versione 1.9.29 era nata come strumento sperimentale per lavorare su pochi fogli, con percorsi distribuiti, output che potevano sovrascrivere i file e una gestione dei tag SeString non sufficientemente sicura. Durante i test con `Addon`, `Lobby` e `Item` sono emersi problemi di compatibilità, backup e soprattutto un crash causato dalla scrittura errata di un blocco SQPACK raw.

La 2.0 ricomincia dal progetto isolato e verificabile, mantenendo le traduzioni già esistenti compatibili quando la struttura CSV e i tag vengono preservati.

## Cosa cambia nella 2.0

- Webapp ridisegnata con sezioni separate per estrazione, workspace, compilazione/inject, impostazioni, problemi noti e segnalazioni.
- Un solo percorso di gioco, un percorso principale del progetto e un percorso di test configurabili dalla pagina **Impostazioni**.
- Workspace controllato in `data/csv/current/`, EXD compilati in `data/exd/current/` e cartelle dedicate per backup, export e storico.
- Ogni export e import crea una cartella timestampata senza sovrascrivere automaticamente i file esistenti.
- Filtraggio dei file CSV: la webapp mostra soltanto nomi validi per evitare di usare backup, file `_original`, `_wip` o varianti temporanee.
- Estrazione multipla degli EXH, selezione per categoria e catalogo dei fogli con testo traducibile.
- Supporto operativo per fogli come `Addon`, `Lobby`, `Item`, `Quest`, `EventText`, `Weather` e `CustomTalk`, quando presenti nella build del gioco.
- Parser EXH/EXD con gestione delle varianti, subrow, bitfield, fixed data e string pool.
- Preservazione del fixed data originale: la compilazione modifica soltanto i riferimenti testuali necessari.
- Dizionario dei tag SeString per conservare macro, icone, variabili, newline e altri byte binari senza trasformarli in testo.
- Log di compilazione e inject con confronto in byte tra originale e tradotto, avvisi sui possibili rischi e filtri/ordinamento dei risultati.
- Backup SQPACK iniziale e snapshot del lavoro prima degli import.
- Sezione **Problemi noti** e sistema locale di segnalazione con stato e risposte amministrative.

## Correzione SQPACK verificata

Un crash osservato all’avvio è stato ricondotto a un blocco raw scritto con un’intestazione del tipo `(16, 0, 24, 24)`. Dalamud/Lumina riportava:

```text
failed to inflate block, bytesRead (2) != BlockDataSize (24)
```

Nel writer 2.0 un blocco non compresso usa `CompressedSize = 32000` e mantiene in `UncompressedSize` la dimensione reale del payload. I blocchi compressi conservano invece la dimensione compressa effettiva e vengono verificati prima dell’inject.

Dopo ogni modifica al writer è necessario riavviare il server, perché un processo Uvicorn già attivo può continuare a usare il codice precedente.

## Metodo di lavoro

1. Avviare la webapp.
2. Configurare i tre percorsi in **Impostazioni**.
3. Creare o verificare il backup SQPACK.
4. Esportare uno o più EXH nella cartella storica proposta dall’app.
5. Copiare/importare nel workspace soltanto i CSV validi da tradurre.
6. Controllare tag, RowID, righe mancanti e differenze di dimensione.
7. Compilare prima un foglio o un batch ridotto.
8. Esaminare l’avviso di rischio e il log dettagliato.
9. Eseguire l’inject dopo aver verificato il backup.
10. Avviare il gioco e registrare eventuali problemi nella sezione dedicata.

Per isolare un crash, ripristinare il backup e testare un singolo foglio alla volta. Non usare i file generati direttamente dalla cartella `export/` per l’inject: devono prima essere importati nel workspace.

## Avvio locale

È necessario Python con le dipendenze dell’applicazione, inclusi FastAPI e Uvicorn. Dalla cartella del progetto:

```bash
./start.sh
```

La pagina sarà disponibile su `http://127.0.0.1:8000/`.

Il progetto non include SQPACK, CSV, EXD, backup, log o traduzioni personali. Questi file vengono creati localmente nelle cartelle escluse da Git.

## Segnalazioni online

In locale la sezione **Segnala un problema** salva le richieste in `data/issues.sqlite3`. Per un futuro deployment pubblico servono almeno HTTPS, rate limiting, autenticazione utenti, protezione del token amministrativo e un database adeguato.

Variabili previste dal backend:

```bash
export FFXIV_ADMIN_TOKEN='inserire-un-token-lungo-e-casuale'
export FFXIV_PUBLIC_DEPLOYMENT=1
```

Le API pubbliche sono `POST /api/issues` e `GET /api/issues`; cambio di stato e risposte richiedono l’header `X-Admin-Token`.

## Sicurezza e compatibilità

- Non pubblicare mai il percorso completo della propria installazione, token, backup SQPACK o file di traduzione non revisionati.
- Fare sempre un backup prima dell’inject.
- Un CSV valido non garantisce da solo la sicurezza: fixed data, RowID, subrow, tag e dimensioni dei blocchi devono rimanere coerenti.
- Penumbra non è richiesto dal progetto: l’injector opera direttamente sugli SqPack. Eventuali errori rilevati da Dalamud/Lumina o Penumbra possono essere conseguenze della lettura di un blocco già corrotto.

## Stato del progetto

La 2.0 è una release di consolidamento e test. `Addon` e `Lobby` sono stati verificati con successo; `Item` ha richiesto una correzione specifica del writer SQPACK. I fogli più grandi e le traduzioni complete devono essere testati progressivamente, mantenendo gli snapshot disponibili per il ripristino.
