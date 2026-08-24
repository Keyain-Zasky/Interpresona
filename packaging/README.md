# Pacchetti nativi

La GUI portatile inclusa nella release funziona con Python 3.10+ e Tkinter.
Per evitare che l'utente debba installare Python si possono generare eseguibili
nativi su ogni sistema operativo usando PyInstaller sul sistema stesso:

```sh
python -m pip install -r packaging/requirements-build.txt
python scripts/build_native.py
```

Il risultato è `dist/Interpresona` su Linux/macOS oppure
`dist/Interpresona.exe` su Windows. PyInstaller non è un compilatore
cross-platform: l'eseguibile Windows va costruito su Windows, quello macOS su
macOS e quello Linux su Linux. Il workflow GitHub Actions del progetto esegue
questi tre build su runner nativi e conserva gli artefatti della release.

La versione portatile resta disponibile come fallback per sistemi in cui non si
vuole scaricare un eseguibile nativo.

Il portale espone i pacchetti nativi in `GET /api/v1/version` dentro
`installer_packages` e li serve da `/api/v1/download/installer/{platform}`.
La pubblicazione autenticata dello ZIP avviene tramite
`POST /api/v1/admin/installer`; il workflow usa il secret GitHub
`FFXIV_PORTAL_API_KEY` senza salvarlo nel repository.
