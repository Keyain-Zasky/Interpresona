# Privacy operations

## Dati trattati dal portale

Il portale può trattare account, email, segnalazioni, log inviati
volontariamente, IP tecnico per la prevenzione degli abusi e la preferenza
locale relativa ai servizi esterni. Non sono attivi analytics o pubblicità.
Il log accessi HTTP di Uvicorn è disattivato. Sul reverse proxy Caddy esterno
il solo blocco dei domini FFXIV registra accessi tecnici in un file protetto,
con rotazione e retention massima di 30 giorni; la verifica è stata eseguita
il 24 agosto 2026 e registrata in `FFXIV_PROXY_LOG_RETENTION_VERIFIED=1`.
La conferma formale del titolare resta un passaggio separato.

Interpresona è un progetto indipendente e non commerciale: non vende accessi,
abbonamenti o servizi. Eventuali donazioni tramite Buy Me a Coffee sono
facoltative e non danno diritto a funzioni, assistenza o aggiornamenti esclusivi.

Il widget Buy Me a Coffee viene caricato soltanto dopo una scelta esplicita
dell’utente. La scelta viene salvata in `localStorage`, non in un cookie HTTP,
con versione e scadenza tecnica di 180 giorni; può essere revocata dalla
pagina Cookie. Il riferimento operativo per cookie e strumenti di tracciamento
è costituito dalle [linee guida del Garante](https://www.garanteprivacy.it/temi/cookie);
la configurazione concreta va comunque verificata rispetto ai fornitori
effettivamente attivi.
Le sessioni di account e amministrazione usano invece un cookie tecnico
`HttpOnly`, `Secure` e `SameSite=Lax`; il token Bearer resta disponibile solo
per compatibilità con client non-browser. Le interfacce web non salvano token
nel browser e il cambio password amministrativo revoca tutte le sessioni
precedenti.

Il checkbox della segnalazione esprime il consenso esplicito al trattamento dei
dati inseriti per gestire la richiesta, compresi gli eventuali log facoltativi;
il testo rimanda all’informativa e il consenso viene registrato con data e
versione della privacy notice. La revoca o le richieste relative ai dati
restano possibili tramite il contatto privacy.

Finché la checklist non riporta `publication_allowed=true`, il portale applica
un blocco preventivo sulle nuove registrazioni e sulle nuove segnalazioni. In
questo modo una privacy notice ancora marcata come “in configurazione” non
viene usata per raccogliere nuovi dati personali. Il gate non impedisce
all’amministratore di completare la configurazione né agli utenti già esistenti
di esercitare i propri diritti.

Ogni segnalazione conserva anche la versione della privacy notice visualizzata
al momento dell’invio. I log vengono limitati a 30.000 caratteri e passano da
una redazione automatica di bearer token, API key, password, token noti e chiavi
private prima di essere scritti nel database; l’utente deve comunque evitare di
inviare segreti.

## Diritti disponibili nell’app

Gli utenti autenticati possono:

- esportare i dati associati al proprio account;
- chiedere la cancellazione dell’account e delle relative segnalazioni;
- consultare lo storico delle proprie richieste;
- cambiare la propria password; l’operazione revoca le sessioni precedenti;
- inviare richieste privacy al contatto pubblicato nell’informativa.

L’amministratore può sospendere o riattivare account utente, revocarne le
sessioni, eliminare account e gestire lo stato delle segnalazioni. La
sospensione revoca immediatamente le sessioni dell’utente. L’account
amministrativo non è eliminabile o sospendibile dall’interfaccia per evitare
di perdere l’unico accesso di gestione.

L’elenco account dell’area admin è filtrabile per email e stato; restituisce
solo i campi operativi necessari e non consente ricerche o esportazioni di
password, IP o contenuti dei ticket. Mostra soltanto contatori di sessioni
attive e segnalazioni associate per facilitare la gestione operativa.

## Retention

La configurazione attuale prevede 30 giorni per gli IP e 365 giorni per i
ticket chiusi o risolti. La pulizia viene eseguita all’avvio e periodicamente
durante il normale traffico del servizio; nello stesso ciclo vengono rimosse
anche le sessioni scadute.

## Stato della configurazione del titolare

Il 24 agosto 2026 il titolare ha confermato nell’area operativa: account
opzionale per lo storico delle segnalazioni, consenso esplicito per le nuove
segnalazioni, legittimo interesse per la sicurezza, infrastruttura gestita
direttamente e retention prevista di 30 giorni per i log del reverse proxy.
L’indirizzo civico completo resta non pubblicato; la pagina mostra soltanto la
città.

La verifica tecnica del reverse proxy e la revisione del titolare sono state
completate il 24 agosto 2026. Le nuove segnalazioni anonime e la creazione
facoltativa degli account sono quindi attive.

La pubblicazione dell’indirizzo civico è controllabile separatamente dal
pannello admin e, per impostazione predefinita, resta disattivata; il dato
completo può essere conservato nell’area amministrativa senza essere mostrato
nel sito pubblico.

Le basi giuridiche devono essere valutate dal titolare per ogni finalità e
indicate nell’informativa prima della pubblicazione. Il riferimento operativo
è l’articolo 13 del GDPR e la guida EDPB sulle basi giuridiche e sui diritti
degli interessati. Il pulsante di conferma nell’area admin registra soltanto
che il titolare dichiara di avere effettuato questa revisione: non è una
certificazione automatica né sostituisce un parere professionale. Per la
verifica usare la [guida EDPB sulle basi giuridiche](https://www.edpb.europa.eu/sme/be-compliant/process-personal-data-lawfully_en)
e il [materiale del Garante sulla base giuridica](https://www.garanteprivacy.it/documents/10160/0/VADEMECUM%2B-%2BSocial%2BPrivacy%2B-%2BCome%2Btutelarsi%2Bnell%27epoca%2Bdei%2Bsocial%2Bmedia-%2B2025.pdf/6fa4e17b-835e-80d4-d2c6-533adb2bd6ea?download=true&version=5.0).
