# Installer standalone Interpresona

Il pacchetto pubblico contiene già il motore EXH/EXD e il catalogo EXH: non
serve scaricare altri file dal progetto. Richiede Python 3.10 o superiore, ma
non richiede un server web o mod/plugin esterni. Prima di ogni inject salva in `backups/AAAAMMGG-HHMMSS/`
gli SQPACK effettivamente coinvolti e scrive un report in `logs/`.

## Primo utilizzo

Estrai prima tutto lo ZIP in una cartella. Poi apri
`Interpresona-Installer.bat` su Windows, esegui `sh Interpresona-Installer.sh`
su Linux oppure apri `Interpresona-Installer.command` su macOS. In alternativa sono disponibili
anche `install.bat` e `install.sh`. Avviandoli senza argomenti si apre la
GUI guidata, che chiede il percorso di FFXIV, controlla la release, mostra il
progresso dei download e propone installazione o ripristino con conferma.
Sono accettati sia la cartella SQPACK/ffxiv sia la normale cartella di gioco.

La modalità testuale resta disponibile passando argomenti ai launcher oppure
avviando direttamente `interpresona_installer.py`, utile per automazioni e
ambienti senza Tkinter. La GUI non modifica mai il gioco senza conferma.
Se Python non è presente, il launcher mostra il collegamento ufficiale per
installare Python 3.10 o superiore.

Linux/macOS:

```sh
./installer/install.sh configure \
  --game "/percorso/alla/cartella/sqpack/ffxiv" \
  --project "/percorso/al/progetto"
./installer/install.sh status
```

Windows:

```bat
installer\install.bat configure --game "C:\\...\\game\\sqpack\\ffxiv" --project "C:\\Interpresona"
```

Controllo degli aggiornamenti senza modificare il gioco:

```sh
./installer/install.sh update --check
```

Installazione della release EXD precompilata:

```sh
./installer/install.sh update
./installer/install.sh install --all
```

Prima di un inject reale si può usare una verifica senza modifiche:

```sh
./installer/install.sh install --sheet addon --sheet lobby --dry-run
```

Compilazione manuale dei CSV presenti in `runtime/workspace/` e inject (solo
per lo studio locale o per release legacy):

```sh
./installer/install.sh install --source csv --sheet addon
```

Per installare tutto il catalogo verificato:

```sh
./installer/install.sh install --all
```

Per l’uso pubblico, dopo aver configurato il percorso una volta, il comando
unico scarica gli EXD precompilati, verifica checksum e patch, crea il backup
e inietta:

```sh
./installer/install.sh apply
```

Per provare l’intero flusso senza scrivere gli SQPACK:

```sh
./installer/install.sh apply --dry-run
```

Se è stato configurato un secondo SQPACK con `configure --test`, si può usare
`--target test` per una prova isolata.

Ripristino dell’ultimo backup:

```sh
./installer/install.sh restore
```

Il gioco deve essere chiuso durante installazione e ripristino. Il percorso
indicato può essere la cartella di FFXIV oppure quella che contiene direttamente
`0a0000.win32.index` e i relativi `.dat`. Dopo ogni installazione l’app mostra
il percorso del backup e il comando per ripristinarlo.
