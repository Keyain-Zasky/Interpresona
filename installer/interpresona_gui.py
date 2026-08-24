#!/usr/bin/env python3
"""Interfaccia grafica multipiattaforma per l'installer Interpresona.

Usa solo Tkinter e il motore già presente nel pacchetto: non richiede
framework web, plugin o un servizio locale. Le operazioni che modificano il
gioco richiedono sempre una conferma esplicita.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import threading
import traceback
import webbrowser
import zipfile
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText
except ImportError as exc:  # pragma: no cover - dipende dal sistema operativo
    raise SystemExit("Tkinter non è disponibile. Usa il launcher testuale per installare il pacchetto GUI.") from exc

from interpresona_installer import (
    APP_VERSION,
    DEFAULT_API,
    DEFAULT_CONFIG,
    absolute,
    api_url,
    apply_pending_app_update,
    check_game,
    download_archive,
    fetch_json,
    install,
    installed_release,
    latest_backup,
    load_config,
    project_paths,
    resolve_game_path,
    restore_backup,
    save_config,
    installer_platform_key,
    stage_native_application_update,
    update_from_server,
)


def application_dir() -> Path:
    """Directory realmente aggiornabile, anche quando l'app è congelata."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


class InterpresonaGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Interpresona · Traduzione italiana FFXIV")
        self.geometry("840x650")
        self.minsize(700, 540)
        self.config_path = absolute(DEFAULT_CONFIG)
        self.config_data = load_config(self.config_path)
        self.remote = None
        self.busy = False
        self._build_style()
        self._build_ui()
        self._load_config_fields()
        self.after(250, self.check_status)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("TkDefaultFont", 18, "bold"))
        style.configure("Subtitle.TLabel", foreground="#52606d")
        style.configure("Section.TLabelframe.Label", font=("TkDefaultFont", 11, "bold"))
        style.configure("Primary.TButton", padding=(12, 7))
        style.configure("Danger.TButton", padding=(12, 7))

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=18)
        root.pack(fill="both", expand=True)
        header = ttk.Frame(root)
        header.pack(fill="x")
        ttk.Label(header, text="Interpresona", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text=f"Traduzione italiana di Final Fantasy XIV · app {APP_VERSION}", style="Subtitle.TLabel").pack(anchor="w", pady=(2, 12))

        paths = ttk.LabelFrame(root, text="1 · Percorso del gioco", style="Section.TLabelframe")
        paths.pack(fill="x", pady=(0, 10))
        self.game_var = tk.StringVar()
        row = ttk.Frame(paths)
        row.pack(fill="x", padx=10, pady=10)
        ttk.Entry(row, textvariable=self.game_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Scegli…", command=self.choose_game).pack(side="left", padx=(8, 0))
        self.path_status = ttk.Label(paths, text="Inserisci la cartella del gioco o SQPACK/ffxiv.", style="Subtitle.TLabel")
        self.path_status.pack(anchor="w", padx=10, pady=(0, 10))

        actions = ttk.LabelFrame(root, text="2 · Aggiornamento e installazione", style="Section.TLabelframe")
        actions.pack(fill="x", pady=(0, 10))
        buttons = ttk.Frame(actions)
        buttons.pack(fill="x", padx=10, pady=(10, 6))
        self.check_button = ttk.Button(buttons, text="Verifica aggiornamenti", command=self.check_status)
        self.check_button.pack(side="left")
        self.update_button = ttk.Button(buttons, text="Scarica traduzione", command=self.download_translation)
        self.update_button.pack(side="left", padx=8)
        self.apply_button = ttk.Button(buttons, text="Aggiorna e applica al gioco", style="Primary.TButton", command=self.apply_translation)
        self.apply_button.pack(side="left")
        self.restore_button = ttk.Button(buttons, text="Ripristina backup", style="Danger.TButton", command=self.restore_translation)
        self.restore_button.pack(side="right")
        self.release_label = ttk.Label(actions, text="Release: verifica in corso…", style="Subtitle.TLabel")
        self.release_label.pack(anchor="w", padx=10, pady=(0, 8))
        self.progress = ttk.Progressbar(actions, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=10, pady=(0, 4))
        self.progress_label = ttk.Label(actions, text="Pronto", style="Subtitle.TLabel")
        self.progress_label.pack(anchor="w", padx=10, pady=(0, 10))

        app_update = ttk.LabelFrame(root, text="3 · Aggiornamento del software", style="Section.TLabelframe")
        app_update.pack(fill="x", pady=(0, 10))
        app_row = ttk.Frame(app_update)
        app_row.pack(fill="x", padx=10, pady=10)
        self.app_status = ttk.Label(app_row, text="Controllo versione non ancora eseguito.", style="Subtitle.TLabel")
        self.app_status.pack(side="left", fill="x", expand=True)
        self.app_button = ttk.Button(app_row, text="Aggiorna applicazione", command=self.update_application)
        self.app_button.pack(side="right")

        log_frame = ttk.LabelFrame(root, text="Registro operazioni", style="Section.TLabelframe")
        log_frame.pack(fill="both", expand=True)
        self.log = ScrolledText(log_frame, height=10, wrap="word", state="disabled", font=("TkFixedFont", 9))
        self.log.pack(fill="both", expand=True, padx=8, pady=8)
        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(8, 0))
        ttk.Button(footer, text="Apri portale", command=lambda: webbrowser.open("https://ffxiv.paolozzi.me")).pack(side="left")
        ttk.Label(footer, text="Il gioco deve essere chiuso durante l’applicazione o il ripristino.", style="Subtitle.TLabel").pack(side="right")

    def _load_config_fields(self) -> None:
        self.game_var.set(str(self.config_data.get("game_sqpack", "")))

    def write_log(self, message: str) -> None:
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"[{stamp}] {message}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def choose_game(self) -> None:
        selected = filedialog.askdirectory(title="Seleziona la cartella di FFXIV o SQPACK/ffxiv")
        if selected:
            self.game_var.set(selected)
            self.save_game_path()

    def save_game_path(self) -> Path | None:
        raw = self.game_var.get().strip()
        if not raw:
            self.path_status.configure(text="Percorso mancante.")
            return None
        game = resolve_game_path(raw)
        if not (game / "0a0000.win32.index").is_file():
            self.path_status.configure(text="SQPACK non trovato: seleziona la cartella che contiene 0a0000.win32.index.")
            return None
        self.config_data["game_sqpack"] = str(game)
        save_config(self.config_path, self.config_data)
        self.path_status.configure(text=f"SQPACK trovato: {game}")
        return game

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for button in (self.check_button, self.update_button, self.apply_button, self.restore_button, self.app_button):
            button.configure(state=state)

    def _progress(self, fraction: float, message: str) -> None:
        self.after(0, lambda: (self.progress.configure(value=fraction * 100), self.progress_label.configure(text=message)))

    def _run(self, title: str, operation, on_success=None) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self.progress.configure(value=0)
        self.progress_label.configure(text=title)

        def worker() -> None:
            try:
                result = operation()
            except (Exception, SystemExit) as exc:  # noqa: BLE001 - mostrato nella GUI
                details = str(exc)
                self.after(0, lambda: self._operation_failed(details))
                return
            self.after(0, lambda: self._operation_done(result, on_success))

        threading.Thread(target=worker, daemon=True).start()

    def _operation_failed(self, details: str) -> None:
        self._set_busy(False)
        self.progress_label.configure(text="Operazione non riuscita")
        self.write_log("ERRORE: " + details)
        messagebox.showerror("Interpresona", details)

    def _operation_done(self, result, callback) -> None:
        self._set_busy(False)
        self.progress.configure(value=100)
        self.progress_label.configure(text="Operazione completata")
        if callback:
            callback(result)

    def check_status(self) -> None:
        if self.busy:
            return
        game = self.save_game_path()
        if not game:
            self.release_label.configure(text="Release: configura prima il percorso del gioco.")
            return

        def operation():
            api = str(self.config_data.get("distribution_api", DEFAULT_API)).rstrip("/")
            remote = fetch_json(api + "/version")
            project, _, compiled = project_paths(self.config_data)
            local = installed_release(compiled)
            return remote, local

        def done(value):
            remote, local = value
            self.remote = remote
            remote_id = (remote.get("build_id"), remote.get("version"))
            local_source = local.get("source_manifest", local)
            update = remote_id != (local_source.get("build_id"), local_source.get("version"))
            label = f"Release {remote.get('version', 'n/d')} · patch {remote.get('game_patch', 'n/d')} · {remote.get('total_files', '?')} CSV"
            self.release_label.configure(text=label + (" · aggiornamento disponibile" if update else " · già aggiornata"))
            native = (remote.get("installer_packages") or {}).get(installer_platform_key())
            remote_app = (native or {}).get("version") or remote.get("installer_version") or remote.get("version")
            suffix = " · pacchetto nativo disponibile" if native else " · pacchetto portatile"
            self.app_status.configure(text=f"Software: {APP_VERSION} · disponibile: {remote_app or 'n/d'}{suffix}")
            self.write_log("Controllo completato: " + label)

        self._run("Controllo del portale…", operation, done)

    def _require_game(self) -> bool:
        return self.save_game_path() is not None

    def download_translation(self) -> None:
        if not self._require_game() or not messagebox.askyesno("Scarica aggiornamento", "Scaricare e verificare l’ultima traduzione?\n\nNessun file di gioco verrà modificato."):
            return
        def operation():
            self.after(0, self.write_log, "Download release avviato.")
            return update_from_server(self.config_data, self._progress)
        self._run("Download della traduzione…", operation, lambda _: self.write_log("Traduzione aggiornata e verificata."))

    def apply_translation(self) -> None:
        if not self._require_game() or not messagebox.askyesno("Applica traduzione", "Scaricare l’ultima release, creare un backup e applicarla al gioco?\n\nIl gioco deve essere chiuso."):
            return
        def operation():
            self.after(0, self.write_log, "Aggiornamento release avviato.")
            update_from_server(self.config_data, self._progress)
            args = type("Args", (), {"target": "game", "force": False, "dry_run": False, "source": "exd", "sheet": None, "all": True})()
            install(args, self.config_data, self.config_path, self._progress)
            return True
        self._run("Aggiornamento e applicazione…", operation, lambda _: self.write_log("Backup creato e traduzione applicata."))

    def restore_translation(self) -> None:
        if not messagebox.askyesno("Ripristina backup", "Ripristinare l’ultimo backup del gioco?\n\nIl gioco deve essere chiuso."):
            return
        def operation():
            project, _, _ = project_paths(self.config_data)
            restore_backup(project, None)
            return True
        self._run("Ripristino backup…", operation, lambda _: self.write_log("Ripristino completato."))

    def update_application(self) -> None:
        if not messagebox.askyesno("Aggiorna software", "Controllare e installare una nuova versione dell’applicazione?\n\nLe impostazioni e i backup verranno conservati."):
            return
        def operation():
            api = str(self.config_data.get("distribution_api", DEFAULT_API)).rstrip("/")
            remote = fetch_json(api + "/version")
            native_mode = getattr(sys, "frozen", False)
            packages = remote.get("installer_packages") or {}
            package = packages.get(installer_platform_key()) if native_mode else remote.get("installer_package")
            package = package or {}
            url = package.get("download_url")
            expected = package.get("sha256")
            if not url or not expected:
                if native_mode:
                    raise RuntimeError(f"Il portale non pubblica ancora un pacchetto nativo per {installer_platform_key()}.")
                raise RuntimeError("Il portale non pubblica ancora un pacchetto aggiornato dell’applicazione.")
            with tempfile.TemporaryDirectory(prefix="interpresona-app-update-") as tmp:
                archive = download_archive(api_url(api, str(url)), str(expected), Path(tmp), "installer", self._progress)
                version = str(package.get("version") or remote.get("installer_version") or remote.get("version") or APP_VERSION)
                if native_mode:
                    stage_native_application_update(archive, version)
                else:
                    staging = Path(tmp) / "staging"
                    staging.mkdir()
                    with zipfile.ZipFile(archive) as bundle:
                        for raw_name in bundle.namelist():
                            member = raw_name.replace("\\", "/")
                            if not member or member.endswith("/") or member.startswith("/") or ".." in Path(member).parts:
                                raise RuntimeError("Pacchetto aggiornamento non sicuro.")
                            source = bundle.extract(raw_name, staging)
                            target = application_dir() / member
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(source, target)
            return version, native_mode
        def done(result):
            version, native_mode = result
            if native_mode:
                self.write_log(f"Pacchetto nativo {version} scaricato e verificato. Riavvia l’app per completare l’aggiornamento.")
            else:
                self.write_log(f"Software aggiornato alla versione {version}. Riavvia l’applicazione per usare la nuova versione.")
            messagebox.showinfo("Aggiornamento completato", "Aggiornamento scaricato e verificato. Chiudi e riapri l’applicazione per completarlo.")
        self._run("Aggiornamento applicazione…", operation, done)


if __name__ == "__main__":
    pending = apply_pending_app_update()
    if pending:
        print(pending)
    app = InterpresonaGUI()
    app.mainloop()
