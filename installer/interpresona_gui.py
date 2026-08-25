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
        self.geometry("1000x720")
        self.minsize(820, 620)
        self.config_path = absolute(DEFAULT_CONFIG)
        self.config_data = load_config(self.config_path)
        self.remote = None
        self.busy = False
        self._build_style()
        self._build_ui()
        self._load_config_fields()
        self.after(250, self.check_status)

    def _build_style(self) -> None:
        self.colors = {
            "bg": "#0b1020",
            "surface": "#121a2b",
            "surface_2": "#172238",
            "line": "#263653",
            "text": "#f3f6ff",
            "muted": "#9baac2",
            "cyan": "#70dcff",
            "violet": "#a99aff",
            "green": "#83e6b0",
            "yellow": "#ffdb72",
            "red": "#ff8f9c",
        }
        self.configure(bg=self.colors["bg"])
        self.option_add("*Font", ("Segoe UI", 10))
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Dark.TEntry", fieldbackground=self.colors["bg"], background=self.colors["bg"], foreground=self.colors["text"], bordercolor=self.colors["line"], insertcolor=self.colors["text"], padding=9)
        style.configure("Accent.Horizontal.TProgressbar", troughcolor=self.colors["bg"], background=self.colors["cyan"], bordercolor=self.colors["bg"], lightcolor=self.colors["cyan"], darkcolor=self.colors["cyan"], thickness=8)

    def _button(self, parent, text, command, *, kind="secondary", width=None):
        styles = {
            "primary": (self.colors["cyan"], "#07111c", self.colors["cyan"]),
            "secondary": (self.colors["surface_2"], self.colors["text"], self.colors["line"]),
            "quiet": (self.colors["surface"], self.colors["muted"], self.colors["line"]),
            "danger": ("#482332", "#ffb3bd", "#754052"),
        }
        background, foreground, border = styles[kind]
        options = {
            "text": text,
            "command": command,
            "bg": background,
            "fg": foreground,
            "activebackground": border,
            "activeforeground": self.colors["text"],
            "relief": "flat",
            "bd": 0,
            "highlightthickness": 1,
            "highlightbackground": border,
            "highlightcolor": self.colors["cyan"],
            "padx": 13,
            "pady": 8,
            "cursor": "hand2",
        }
        if width:
            options["width"] = width
        return tk.Button(parent, **options)

    def _build_ui(self) -> None:
        c = self.colors
        root = tk.Frame(self, bg=c["bg"])
        root.pack(fill="both", expand=True, padx=28, pady=24)

        header = tk.Frame(root, bg=c["bg"])
        header.pack(fill="x", pady=(0, 22))
        brand_row = tk.Frame(header, bg=c["bg"])
        brand_row.pack(side="left", anchor="w")
        tk.Label(brand_row, text="✦", bg=c["cyan"], fg="#07111c", font=("Segoe UI", 18, "bold"), width=2, height=1).pack(side="left", padx=(0, 12))
        brand = tk.Frame(brand_row, bg=c["bg"])
        brand.pack(side="left")
        tk.Label(brand, text="INTERPRESONA", bg=c["bg"], fg=c["text"], font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(brand, text="Traduzione italiana per Final Fantasy XIV", bg=c["bg"], fg=c["muted"], font=("Segoe UI", 10)).pack(anchor="w")
        badge = tk.Label(header, text=f"APP {APP_VERSION}  •  PRONTA", bg="#19382e", fg=c["green"], font=("Segoe UI", 9, "bold"), padx=12, pady=7)
        badge.pack(side="right", anchor="n")

        content = tk.Frame(root, bg=c["bg"])
        content.pack(fill="both", expand=True)
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=2)
        content.grid_rowconfigure(2, weight=1)

        paths = tk.Frame(content, bg=c["surface"], highlightthickness=1, highlightbackground=c["line"])
        paths.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        path_title = tk.Frame(paths, bg=c["surface"])
        path_title.pack(fill="x", padx=18, pady=(15, 3))
        tk.Label(path_title, text="PERCORSO DEL GIOCO", bg=c["surface"], fg=c["violet"], font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Label(path_title, text="Richiesto una sola volta", bg=c["surface"], fg=c["muted"], font=("Segoe UI", 9)).pack(side="right")
        self.game_var = tk.StringVar()
        path_row = tk.Frame(paths, bg=c["surface"])
        path_row.pack(fill="x", padx=18, pady=(7, 3))
        ttk.Entry(path_row, textvariable=self.game_var, style="Dark.TEntry").pack(side="left", fill="x", expand=True)
        self._button(path_row, "Scegli cartella", self.choose_game, kind="secondary").pack(side="left", padx=(10, 0))
        self.path_status = tk.Label(paths, text="Seleziona la cartella di FFXIV oppure direttamente SQPACK/ffxiv.", bg=c["surface"], fg=c["muted"], anchor="w", font=("Segoe UI", 9))
        self.path_status.pack(fill="x", padx=18, pady=(3, 15))

        actions = tk.Frame(content, bg=c["surface"], highlightthickness=1, highlightbackground=c["line"])
        actions.grid(row=1, column=0, sticky="nsew", padx=(0, 14), pady=(0, 14))
        tk.Label(actions, text="AGGIORNAMENTO E INSTALLAZIONE", bg=c["surface"], fg=c["violet"], font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=18, pady=(16, 2))
        self.release_label = tk.Label(actions, text="Release: verifica in corso…", bg=c["surface"], fg=c["text"], anchor="w", justify="left", wraplength=540, font=("Segoe UI", 11, "bold"))
        self.release_label.pack(fill="x", padx=18, pady=(4, 14))
        self.progress = ttk.Progressbar(actions, mode="determinate", maximum=100, style="Accent.Horizontal.TProgressbar")
        self.progress.pack(fill="x", padx=18, pady=(0, 5))
        self.progress_label = tk.Label(actions, text="Pronto", bg=c["surface"], fg=c["muted"], anchor="w", font=("Segoe UI", 9))
        self.progress_label.pack(fill="x", padx=18, pady=(0, 15))
        action_row = tk.Frame(actions, bg=c["surface"])
        action_row.pack(fill="x", padx=18, pady=(0, 17))
        self.apply_button = self._button(action_row, "Aggiorna e applica", self.apply_translation, kind="primary")
        self.apply_button.pack(side="left")
        self.update_button = self._button(action_row, "Scarica solo", self.download_translation, kind="secondary")
        self.update_button.pack(side="left", padx=(8, 0))
        self.check_button = self._button(action_row, "Verifica", self.check_status, kind="quiet")
        self.check_button.pack(side="right")

        side = tk.Frame(content, bg=c["bg"])
        side.grid(row=1, column=1, sticky="nsew", pady=(0, 14))
        app_update = tk.Frame(side, bg=c["surface"], highlightthickness=1, highlightbackground=c["line"])
        app_update.pack(fill="x", pady=(0, 14))
        tk.Label(app_update, text="SOFTWARE", bg=c["surface"], fg=c["violet"], font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=18, pady=(16, 3))
        self.app_status = tk.Label(app_update, text="Controllo versione non ancora eseguito.", bg=c["surface"], fg=c["muted"], anchor="w", justify="left", wraplength=300, font=("Segoe UI", 9))
        self.app_status.pack(fill="x", padx=18, pady=(0, 12))
        self.app_button = self._button(app_update, "Aggiorna software", self.update_application, kind="secondary")
        self.app_button.pack(anchor="w", padx=18, pady=(0, 17))

        help_card = tk.Frame(side, bg=c["surface"], highlightthickness=1, highlightbackground=c["line"])
        help_card.pack(fill="x")
        tk.Label(help_card, text="COME FUNZIONA", bg=c["surface"], fg=c["violet"], font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=18, pady=(16, 6))
        tk.Label(help_card, text="1  Chiudi il gioco\n2  Verifica la release\n3  Conferma l’applicazione\n\nOgni inject crea prima un backup.", bg=c["surface"], fg=c["muted"], justify="left", anchor="w", font=("Segoe UI", 9), pady=2).pack(fill="x", padx=18, pady=(0, 16))

        log_frame = tk.Frame(content, bg=c["surface"], highlightthickness=1, highlightbackground=c["line"])
        log_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(0, 14))
        log_header = tk.Frame(log_frame, bg=c["surface"])
        log_header.pack(fill="x", padx=18, pady=(11, 0))
        tk.Label(log_header, text="REGISTRO OPERAZIONI", bg=c["surface"], fg=c["violet"], font=("Segoe UI", 9, "bold")).pack(side="left")
        self.restore_button = self._button(log_header, "Ripristina ultimo backup", self.restore_translation, kind="danger")
        self.restore_button.pack(side="right")
        self.log = ScrolledText(log_frame, height=7, wrap="word", state="disabled", font=("Consolas", 9), bg="#0a101d", fg="#b9c8de", insertbackground=c["text"], relief="flat", bd=0, padx=12, pady=10)
        self.log.pack(fill="both", expand=True, padx=18, pady=(8, 14))

        footer = tk.Frame(root, bg=c["bg"])
        footer.pack(fill="x")
        self._button(footer, "Apri portale", lambda: webbrowser.open("https://ffxiv.paolozzi.me"), kind="quiet").pack(side="left")
        tk.Label(footer, text="Il gioco deve essere chiuso durante installazione e ripristino.", bg=c["bg"], fg=c["muted"], font=("Segoe UI", 9)).pack(side="right")

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
