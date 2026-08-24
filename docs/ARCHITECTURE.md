# Architettura Interpresona 2

## Obiettivo

Interpresona è divisa in tre componenti con responsabilità separate:

1. **Admin Studio locale**: estrazione EXH/EXD, gestione CSV e tag, compilazione,
   audit dei byte, test e inject diretto negli SQPACK.
2. **Portale di distribuzione**: conserva soltanto gli artefatti approvati,
   pubblica manifest e checksum e raccoglie le segnalazioni degli
   utenti.
3. **Installer pubblico**: chiede il percorso del gioco, controlla gli
   aggiornamenti, scarica gli EXD precompilati dal manifest, verifica checksum
   e patch, crea il backup e applica la versione compatibile; mantiene anche un
   percorso esplicito di ripristino.

Il motore `app/ffxiv_engine.py` resta l’unica implementazione di parsing e
scrittura EXH/EXD. L’interfaccia web e l’installer lo utilizzano senza
duplicarne la logica.

Lo Studio espone anche una ricerca nel dizionario traduzioni CSV autorevole
del glossario Gemini. Il file viene aperto esclusivamente in lettura, con
cache invalidata da modifica di timestamp o dimensione; la webapp non copia e
non sovrascrive il file sorgente.

Lo Studio locale viene servito solo su loopback. Le richieste mutative con
`Origin` o `Referer` esterni vengono rifiutate e la sua documentazione FastAPI
resta disabilitata; i percorsi di gioco, sorgente, workspace e output vengono
letti dalle impostazioni locali, senza directory legacy hardcoded.

## Flusso amministratore

```text
SQPACK originale
      ↓ estrazione
CSV + _tags.json + _meta.json
      ↓ traduzione e audit
EXD compilati → test locale → inject di prova
      ↓ approvazione
Bundle di distribuzione → manifest → portale HTTPS
```

Il bundle pubblico deve contenere il nome EXH canonico, i CSV e i sidecar
necessari alla compilazione. I nomi descrittivi come `Items_Equipment_...csv`
sono utili solo come etichette: non devono essere usati come nome tecnico del
foglio durante l’installazione.

## Flusso utente

```text
installer → percorso SQPACK → GET /manifest → confronto release
         → download EXD ZIP → verifica SHA-256 → backup locale
         → inject → report/rollback
```

L’installer non deve contenere API key di amministrazione. Un endpoint pubblico
e HTTPS non richiede segreti nel client; la sicurezza deriva da checksum,
checksum del manifest, validazione dei file e backup. Un eseguibile offuscato non
può nascondere realmente un segreto distribuito all’utente.

## API di distribuzione

Il contratto minimo è:

- `GET /healthz`: controllo minimale di disponibilità del portale, senza dati
  di progetto;
- `GET /api/v1/version`: versione, patch e build;
- `GET /api/v1/manifest`: elenco tecnico per l'installer con `sheet`, percorso,
  categoria, righe e SHA-256; non contiene link pubblici ai singoli CSV;
- `GET /api/v1/download/latest`: bundle CSV/sidecar;
- `GET /api/v1/download/installer`: pacchetto dell'installer pubblico;
- `POST /api/v1/admin/publish`: endpoint amministrativo autenticato che riceve
  il solo `exd_archive` già compilato; CSV e sidecar restano locali e sono
  opzionali soltanto per eventuali archivi interni. Il server verifica
  manifest, checksum e integrità ZIP prima di sostituire il pacchetto attivo.
  Non viene usato dal client pubblico; il token tecnico, se configurato, è
  limitato alla pubblicazione automatizzata e non autorizza le altre funzioni
  admin;
- `POST /api/v1/support/tickets`: segnalazione utente con identificativo
   installazione e log sanitizzato;
- `POST /api/v1/auth/register` e `/api/v1/auth/login`: account utente
  opzionale per seguire le proprie segnalazioni; il browser riceve un cookie
  tecnico `HttpOnly`, `Secure` e `SameSite=Lax`, mentre il Bearer resta per
  client compatibili;
- `POST /api/v1/auth/change-password`: cambio password con verifica della
  password attuale e revoca delle sessioni precedenti;
- `GET /api/v1/support/mine`: storico dell’utente autenticato;
- `POST /api/v1/admin/login`: accesso amministratore separato dal client
  pubblico;
- `GET/POST/DELETE /api/v1/admin/releases/{release_id}`: gestione protetta dei
  metadati e degli snapshot storici; la release attiva può essere modificata,
  mentre la cancellazione è riservata agli snapshot non attivi;
- `GET /api/v1/admin/audit`: registro amministrativo protetto, senza segreti o
  contenuti dei ticket;
- `GET /api/v1/admin/compliance`: checklist tecnica e legale preliminare per
  l'amministratore;
- `POST /api/v1/admin/compliance/confirm`: registra la conferma esplicita del
  titolare dopo la revisione umana; ogni modifica successiva ai dati legali la
  annulla;
- `GET/PATCH /api/v1/admin/tickets`: gestione amministrativa delle richieste.
- `POST /api/v1/admin/users/{user_id}/status`: sospensione o riattivazione
  protetta degli account non amministrativi, con revoca delle sessioni in caso
  di sospensione.

Le richieste mutative che presentano un cookie di sessione devono avere un
header `Origin` tra quelli configurati; un’origine esterna viene rifiutata.
Questo aggiunge una protezione CSRF oltre al CORS senza impedire ai client
non-browser autenticati con Bearer di funzionare. Il token tecnico è riservato
alle operazioni di pubblicazione/rebuild e non sostituisce la sessione admin.

Le operazioni di pubblicazione devono essere atomiche: staging → validazione →
manifest → ZIP → sostituzione della release corrente. Una release precedente
resta conservata per rollback.

I singoli CSV non vengono esposti come download pubblico. Il browser deve
scaricare soltanto l'installer; sarà quest'ultimo a leggere il manifest,
scaricare il bundle completo, verificarne lo SHA-256 e applicarlo dopo il
backup locale.

La pagina `/admin` non riceve file. La pubblicazione parte esclusivamente dal
riquadro **Controllo locale · Pubblicazione release** dell’Admin Studio, dopo
estrazione, traduzione, compilazione e test; il portale riceve soltanto la
release approvata tramite sessione amministrativa.

## Pulizia del repository

Gli script sperimentali e i metadata precedenti sono stati spostati in:

`/home/keyain/ffxiv-project-backups/legacy-diagnostics-2026-08-23/`

Il backup completo precedente alla pulizia è:

`/home/keyain/ffxiv-project-backups/ffxiv-zero-error-translator-before-cleanup-2026-08-23.tar.gz`
