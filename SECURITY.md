# Sicurezza e gestione responsabile

Questo documento descrive le misure tecniche presenti in Interpresona 2 e i
controlli necessari prima della pubblicazione definitiva del portale non commerciale. Non sostituisce
una valutazione legale o una revisione professionale del trattamento dati.

## Misure attive

- HTTPS, HSTS, CSP con nonce per script e fogli di stile HTML, `object-src 'none'`,
  `script-src-attr 'none'`, `frame-ancestors 'none'` e nessuno stile inline,
  `X-Content-Type-Options`, `Referrer-Policy` e `Permissions-Policy`.
- CORS limitato alle origini configurate; in produzione è autorizzato il solo
  portale ufficiale.
- FastAPI Swagger, ReDoc e OpenAPI pubblici disabilitati.
- Accesso admin separato dall’area utente, sessioni browser in cookie
  `HttpOnly`, `Secure` e `SameSite=Lax`, Bearer temporanei per client
  compatibili, password hashate con scrypt, cambio obbligatorio della password
  temporanea, limite massimo di 256 caratteri per evitare input CPU-costosi,
  cambio password autonomo con revoca delle sessioni precedenti e rate limit
  su login, registrazione, cambio password e invio ticket.
- Registro amministrativo interno per pubblicazioni, modifiche e cancellazioni
  di release, gestione utenti, sospensioni/riattivazioni account, impostazioni
  privacy, avanzamento e ticket;
  conserva solo metadati operativi e viene sottoposto a retention.
- Gestione utenti con ricerca e filtri server-side, contatori sintetici,
  sospensione, revoca delle sessioni e cancellazione; il pannello non mostra
  password, IP o contenuti delle segnalazioni nell’elenco account.
- Limite dichiarato di 2 MiB per le richieste API ordinarie e 300 MiB per una
  pubblicazione release, oltre ai limiti per singolo file e per release.
- Database con permessi `600`; il servizio gira come utente non privilegiato
  e systemd applica `ProtectSystem=strict`, `PrivateDevices`, protezione dei
  log/interfacce kernel, limitazione del realtime e architetture syscall native,
  oltre ai privilegi elevabili disabilitati;
  ogni connessione SQLite abilita foreign key, timeout sui lock e schema non
  trusted quando supportato dal runtime.
- Token di pubblicazione separato dal codice applicativo e conservato nel file
  root-only `/etc/ffxiv-portal.env`.
- Controllo OSV eseguito il 2026-08-24 sui pin `fastapi==0.141.1`,
  `uvicorn==0.52.4` e `python-multipart==0.0.32`: nessuna vulnerabilità OSV
  nota al momento del controllo.
- La porta interna Uvicorn `8000` deve restare dietro il reverse proxy; il
  firewall nftables consente il traffico solo dal reverse proxy interno
  `192.168.1.114` e il controllo esterno attuale non la raggiunge direttamente.
  La retention dei log su quel proxy è stata verificata il 24 agosto 2026:
  il blocco Caddy dedicato ai domini FFXIV conserva i log tecnici al massimo
  30 giorni.
- Il rate limit usa l'IP inoltrato soltanto quando il peer è il proxy fidato
  configurato in `FFXIV_TRUSTED_PROXY_IPS`; gli header `X-Forwarded-For` inviati
  da client diretti vengono ignorati e le chiavi temporanee hanno un limite
  massimo in memoria.
- Backup prima dell’inject, checksum SHA-256 del bundle e rollback locale.
- Il checksum SHA-256 dichiarato dall’API è stato confrontato con il bundle
  effettivamente scaricato; anche versione, patch, build ID e conteggio file
  risultano coerenti nel controllo del 24 agosto 2026.
- L’Admin Studio locale ascolta solo su loopback, disabilita la documentazione
  API pubblica e rifiuta richieste mutative provenienti da origini browser
  esterne; i comandi di compilazione e inject restano quindi confinati alla
  sessione locale autorizzata.
- Nessun download pubblico dei singoli CSV: il client usa il bundle tramite
  installer.
- Conservazione automatica: IP 30 giorni, ticket chiusi 365 giorni e sessioni
  scadute rimosse all’avvio e in un ciclo periodico del servizio.
- Il log accessi HTTP predefinito di Uvicorn è disattivato per non conservare
  nel journal una traccia superflua delle richieste e il server header di
  Uvicorn è disattivato; restano errori tecnici e audit amministrativi
  minimizzati.
- Le richieste mutative che presentano un cookie di sessione devono includere
  un `Origin` autorizzato; questo aggiunge una protezione CSRF. I client non
  browser con Bearer restano compatibili; il token tecnico è limitato alle
  operazioni di pubblicazione/rebuild e non apre il pannello admin completo.
- L’IP tecnico non viene restituito dalle API delle segnalazioni o dagli export
  utente; resta soggetto soltanto alla retention configurata per la prevenzione
  degli abusi.
- Se la checklist di compliance non è approvata, il portale applica un gate
  fail-closed: non accetta nuove registrazioni o segnalazioni e mostra il
  motivo agli utenti; le funzioni amministrative e i diritti degli account
  esistenti restano disponibili.
- I log dei ticket vengono troncati e sottoposti a redazione automatica dei
  segreti più comuni; la versione della privacy notice viene associata alla
  presa visione registrata.

## Prima della pubblicazione definitiva

1. Rileggere nella sezione admin l’identità reale del titolare, il contatto
   privacy e le basi già inserite; pubblicare l’indirizzo completo solo se il
   modello del servizio lo rende necessario.
2. Verificare quali fornitori esterni siano effettivamente usati e aggiornare
   l’informativa, inclusa la pagina Cookie.
3. La retention effettiva di 30 giorni sul reverse proxy e il testo del
   consenso alle segnalazioni sono stati verificati il 24 agosto 2026.
4. Ruotare il token API se è stato condiviso in chat, log o sistemi non
   controllati.
5. Conservare i backup del servizio e testare periodicamente il ripristino.

## Segnalazione vulnerabilità

Non pubblicare token, password, log completi o dettagli di exploit nei ticket
pubblici. Inviare una segnalazione privata al contatto indicato nella pagina
Privacy, includendo solo la riproduzione minima necessaria.

## Verifica rapida prima di una release

Il controllo non distruttivo verifica pagine pubbliche, autenticazione, CSRF,
CSP, cookie e testi privacy senza creare account o modificare dati:

```bash
python scripts/portal_smoke.py --base-url https://ffxiv.paolozzi.me
```
