# Checklist di pubblicazione

Questa checklist accompagna ogni aggiornamento del portale Interpresona. I
controlli tecnici verdi non costituiscono una certificazione legale.

## Controlli automatici

- [x] Codice Python compilabile.
- [x] Pagine pubbliche raggiungibili e rotte personali/amministrative protette.
- [x] HSTS, CSP con nonce, `object-src 'none'`, `frame-ancestors 'none'` e
      nessuno stile inline.
- [x] Cookie di sessione `HttpOnly`, `Secure`, `SameSite=Lax`.
- [x] Servizi esterni caricati solo dopo la scelta esplicita dell’utente.
- [x] Il portale non promette notifiche email automatiche che non siano state
      configurate; lo storico delle risposte richiede un account.
- [x] L’IP anti-abuso non viene restituito nelle API delle segnalazioni o negli
      export utente.
- [x] Backup, checksum e rollback del flusso di distribuzione.
- [x] Versione, patch, build ID, conteggio file e checksum del bundle verificati
      contro gli endpoint pubblici; ultimo controllo: 24 agosto 2026.
- [x] `security.txt`, `robots.txt` e sitemap presenti.
- [x] Gate fail-closed: nuove registrazioni e segnalazioni disabilitate finché
      `publication_allowed` non è vero.
- [x] Smoke test:

  ```bash
  python scripts/portal_smoke.py --base-url https://ffxiv.paolozzi.me
  ```

## Conferme manuali obbligatorie

Prima di considerare definitiva l’informativa, il titolare deve:

1. Inserire e verificare identità, qualifica, recapito e contatto privacy.
2. Scegliere e motivare la base giuridica per account, assistenza/segnalazioni
   e sicurezza, in base alle attività effettive.
3. Elencare hosting, reverse proxy, Buy Me a Coffee e ogni altro destinatario,
   indicando eventuali trasferimenti fuori dallo SEE e le garanzie applicabili.
4. Confermare i periodi di conservazione degli IP, dei ticket, degli audit e
   delle sessioni.
5. Verificare la retention dei log sul reverse proxy esterno.
6. Leggere l’informativa pubblica e premere **Conferma revisione del titolare**
   nell’area admin.

La conferma admin registra una revisione umana, ma non sostituisce una
valutazione professionale quando il trattamento o i fornitori lo richiedono.

## Stato dell’audit operativo

Verifica del container di produzione eseguita il 24 agosto 2026:

- servizio `ffxiv-portal.service`: attivo;
- servizio eseguito come utente non privilegiato, con `NoNewPrivileges`,
  `ProtectHome`, `ProtectSystem=strict`, `PrivateTmp`, `PrivateDevices` e
  protezioni kernel attivi;
- regola firewall per il reverse proxy presente;
- retention dei log del reverse proxy: **verificata il 24 agosto 2026** sul
  blocco Caddy dedicato ai domini FFXIV, con retention massima di 30 giorni;
- basi giuridiche e destinatari/trasferimenti: **inseriti e revisionati dal
  titolare il 24 agosto 2026**;
- conferma formale del titolare: **completata il 24 agosto 2026**; la retention
  effettiva del reverse proxy è stata verificata nella stessa data.

La checklist tecnica e la revisione del titolare risultano positive; le nuove
segnalazioni anonime e la creazione facoltativa degli account sono abilitate.

## Vincolo non commerciale

Interpresona è un progetto indipendente e non commerciale. Installer e
traduzione sono gratuiti; Buy Me a Coffee è una donazione facoltativa e non
offre accesso, assistenza o aggiornamenti esclusivi.
