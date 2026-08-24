# Interpresona 2

Interpresona è la suite per estrarre, tradurre, verificare e applicare i dati
testuali di Final Fantasy XIV tramite EXH/EXD e SQPACK.

Il progetto è diviso in:

- `app/`: Admin Studio web locale e motore EXH/EXD;
- `data/csv/current/` del progetto di traduzione è la sorgente CSV ufficiale
  usata dallo Studio locale;
- `installer/`: installer standalone e aggiornamento dal portale HTTPS;
- `runtime/workspace/`: CSV, sidecar e output di lavoro;
- `runtime/exd/`: EXD compilati e manifest;
- la sezione **Dizionario ufficiale** dello Studio legge in sola lettura
  `/home/keyain/.gemini/config/skills/ffxiv-lore-glossary/dizionario_traduzioni.csv`;
  il file viene ricaricato automaticamente quando cambia e può essere
  sostituito per test tramite `INTERPRESONA_GLOSSARY_PATH`;
- `runtime/test/`: sorgente opzionale per prove speciali, separata dalla workspace;
- `server/`: copia versionata del portale di distribuzione remoto;
- `docs/`: architettura e contratto operativo.
- `deploy/`: unità systemd con isolamento del servizio remoto;
- `deploy/nftables.conf`: firewall persistente che limita Uvicorn al reverse proxy;
- `server/requirements.txt`: dipendenze runtime versionate del portale;
- `SECURITY.md`: misure tecniche e checklist prima della pubblicazione;

Avvio Admin Studio:

```sh
sh start.sh
```

Al primo avvio, se non trova un ambiente compatibile, lo script crea
automaticamente `.venv/` nella cartella del progetto e installa le dipendenze
versionate senza modificare il Python di sistema. Gli avvii successivi usano
direttamente quell’ambiente locale.

Uso dell'installer:

```sh
./installer/install.sh configure --game "/percorso/sqpack/ffxiv" --project "$PWD"
./installer/install.sh update --check
./installer/install.sh apply --dry-run
./installer/install.sh apply
```

L'inject reale crea prima un backup timestampato. Il gioco deve essere chiuso.
Il portale pubblica pacchetti nativi per Linux, Windows e macOS quando il build
della piattaforma è disponibile; il pacchetto portatile con GUI Tkinter resta
il fallback universale e richiede Python 3.10 o superiore. Aprendo il launcher
senza argomenti si avvia la procedura guidata, mostra barra di progresso,
aggiornamenti disponibili e propone installazione o ripristino senza conoscere
i comandi CLI. Un aggiornamento nativo viene verificato e completato al
riavvio, così non tenta di sostituire l'eseguibile ancora in uso.
Per il modello completo vedere [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) e
[installer/README.md](installer/README.md). Per sicurezza, privacy e
pubblicazione vedere [SECURITY.md](SECURITY.md),
[docs/PRIVACY_OPERATIONS.md](docs/PRIVACY_OPERATIONS.md) e la
[checklist di compliance](docs/RELEASE_COMPLIANCE_CHECKLIST.md).

Interpresona è un progetto indipendente e non commerciale: installer e
traduzione sono gratuiti. Eventuali donazioni tramite Buy Me a Coffee sono
facoltative e non danno accesso a funzioni, assistenza o aggiornamenti
esclusivi.
