#!/usr/bin/env python3
"""Standalone installer for Interpresona translations.

This tool deliberately uses the project's existing EXH/EXD engine.  It does
not require a web server or external game plugins and never replaces a game
file before creating a timestamped project backup.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

try:
    import certifi
except ImportError:  # pragma: no cover - il pacchetto nativo lo include
    certifi = None


if getattr(sys, "frozen", False):
    # PyInstaller: i dati inclusi sono nella directory temporanea del bundle,
    # mentre l'eseguibile aggiornabile risiede nella sua directory reale.
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    INSTALLER_DIR = Path(sys.executable).resolve().parent
else:
    RESOURCE_DIR = Path(__file__).resolve().parent
    INSTALLER_DIR = RESOURCE_DIR
PROJECT_DIR = Path.home() / "Interpresona"
DEFAULT_CONFIG = Path.home() / ".config" / "interpresona" / "config.json"
DEFAULT_API = "https://ffxiv.paolozzi.me/api/v1"
INSTALLED_RELEASE_FILENAME = "release-manifest.json"
APP_VERSION = "0.4.1"

# The public package carries only the engine and its catalog. Runtime data is
# kept in a user-writable directory instead of beside the downloaded script.
ENGINE_DIR = RESOURCE_DIR / "app"
if not ENGINE_DIR.is_dir():
    ENGINE_DIR = INSTALLER_DIR.parent / "app"
os.environ.setdefault("INTERPRESONA_ENGINE_PROJECT_DIR", str(PROJECT_DIR))
os.environ.setdefault("INTERPRESONA_ENGINE_RUNTIME_DIR", str(PROJECT_DIR / "runtime"))
os.environ.setdefault("INTERPRESONA_ENGINE_CATALOG_FILE", str(ENGINE_DIR / "ffxiv_sheets.txt"))

sys.path.insert(0, str(ENGINE_DIR))
import ffxiv_engine as engine  # noqa: E402


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def default_config() -> dict:
    return {
        "game_sqpack": "",
        "project_dir": str(PROJECT_DIR),
        "test_dir": "",
        "translation_source": "exd",
        "distribution_api": DEFAULT_API,
    }


def load_config(path: Path) -> dict:
    if not path.exists():
        return default_config()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Configurazione non leggibile: {path}: {exc}")
    result = default_config()
    result.update(data if isinstance(data, dict) else {})
    return result


def save_config(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def absolute(value: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(value))))


def project_paths(config: dict) -> tuple[Path, Path, Path]:
    project = absolute(config["project_dir"])
    workspace = project / "runtime" / "workspace"
    compiled = project / "runtime" / "exd"
    return project, workspace, compiled


def installed_release(compiled: Path) -> dict:
    path = compiled / INSTALLED_RELEASE_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def latest_backup(project: Path) -> Path | None:
    root = project / "backups"
    candidates = sorted((item for item in root.iterdir() if item.is_dir()), reverse=True) if root.is_dir() else []
    return candidates[0] if candidates else None


def api_url(api: str, value: str) -> str:
    if value.startswith("/"):
        return api.split("/api/", 1)[0] + value
    return value


def installer_platform_key() -> str:
    """Chiave stabile usata dal portale per i pacchetti nativi."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    architecture = "arm64" if machine in {"aarch64", "arm64"} else "x86_64"
    if system == "windows":
        return "windows-x86_64" if architecture == "x86_64" else f"windows-{architecture}"
    if system == "darwin":
        return f"macos-{architecture}"
    return f"linux-{architecture}"


def apply_pending_app_update() -> str | None:
    """Completa al nuovo avvio un aggiornamento nativo preparato dalla GUI."""
    marker = PROJECT_DIR / "pending-app-update.json"
    if not getattr(sys, "frozen", False) or not marker.is_file():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        staging = absolute(payload["staging"])
        if not staging.is_dir() or PROJECT_DIR not in staging.parents:
            raise ValueError("staging non valido")
        for source in staging.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(staging)
            if any(part in {"", ".", ".."} for part in relative.parts):
                raise ValueError("percorso aggiornamento non valido")
            target = INSTALLER_DIR / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        shutil.rmtree(staging)
        marker.unlink()
        return str(payload.get("version") or "nuova")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return f"Aggiornamento in sospeso non applicato: {exc}"


def stage_native_application_update(archive: Path, version: str) -> Path:
    """Estrae un pacchetto nativo in attesa del riavvio dell'app."""
    staging = PROJECT_DIR / f"pending-app-update-{now_stamp()}"
    suffix = 1
    while staging.exists():
        staging = PROJECT_DIR / f"pending-app-update-{now_stamp()}-{suffix}"
        suffix += 1
    staging.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(archive) as bundle:
            for raw_name in bundle.namelist():
                member = safe_zip_member(raw_name)
                if member.endswith("/"):
                    continue
                destination = staging / member
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(raw_name) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
        executable = "Interpresona.exe" if installer_platform_key().startswith("windows-") else "Interpresona"
        if not (staging / executable).is_file():
            raise SystemExit(f"Pacchetto nativo senza {executable}.")
        marker = PROJECT_DIR / "pending-app-update.json"
        marker.write_text(json.dumps({"version": version, "staging": str(staging)}, indent=2) + "\n", encoding="utf-8")
        return staging
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def configure_engine(config: dict) -> tuple[Path, Path, Path, Path]:
    project, workspace, compiled = project_paths(config)
    game = absolute(config["game_sqpack"])
    csv_source = workspace
    engine.apply_settings({
        "sqpack_dir": str(game),
        "csv_source_dir": str(csv_source),
        "workspace_dir": str(workspace),
        "exd_dir": str(compiled),
    })
    return project, workspace, compiled, game


def check_game(game: Path) -> None:
    index = game / "0a0000.win32.index"
    if not index.is_file():
        raise SystemExit(
            f"SQPACK non trovato in {game}. Seleziona la cartella che contiene "
            "0a0000.win32.index, non la cartella game/ generica."
        )


def resolve_game_path(value: str | Path) -> Path:
    """Accept the exact SQPACK path or a normal FFXIV installation path."""
    original = absolute(value)
    candidates = (
        original,
        original / "sqpack" / "ffxiv",
        original / "game" / "sqpack" / "ffxiv",
        original / "ffxiv",
    )
    for candidate in candidates:
        if (candidate / "0a0000.win32.index").is_file():
            return candidate
    return original


def running_game_processes() -> list[str]:
    names = ("ffxiv_dx11", "ffxivboot", "ffxivlauncher", "xivlauncher")
    found: list[str] = []
    try:
        if platform.system() == "Windows":
            output = subprocess.run(["tasklist"], capture_output=True, text=True, check=False).stdout.lower()
        else:
            output = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True, check=False).stdout.lower()
    except OSError:
        return found
    for line in output.splitlines():
        if any(name in line for name in names):
            found.append(line.strip())
    return found


def selected_sheets(requested: list[str] | None, all_sheets: bool) -> list[str]:
    if all_sheets:
        names = [item["name"] for item in engine.sheet_catalog()]
    else:
        names = requested or []
    result: list[str] = []
    for value in names:
        name = Path(value).stem.lower()
        if name not in result:
            result.append(name)
    if not result:
        raise SystemExit("Indica almeno un EXH oppure usa --all.")
    return result


def manifest_files(compiled: Path, sheet: str) -> list[str]:
    path = compiled / f"{sheet}.manifest.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [str(item) for item in data.get("files", [])]
    except (OSError, json.JSONDecodeError, AttributeError):
        return []


def make_backup(project: Path, game: Path, files: list[str], sheets: list[str]) -> Path:
    root = project / "backups"
    root.mkdir(parents=True, exist_ok=True)
    backup = root / now_stamp()
    suffix = 1
    while backup.exists():
        backup = root / f"{now_stamp()}-{suffix}"
        suffix += 1
    backup.mkdir(parents=True, exist_ok=False)
    copied: list[str] = []
    checksums: dict[str, str] = {}
    targets = [game / "0a0000.win32.index", game / "0a0000.win32.index2"]
    dat_indices: set[int] = set()
    for file_name in files:
        target = engine._index_entry(file_name)
        if target is not None:
            dat_indices.add(int(target[1]))
    targets.extend(game / f"0a0000.win32.dat{index}" for index in sorted(dat_indices))
    for source in targets:
        if source.is_file():
            destination = backup / source.name
            shutil.copy2(source, destination)
            copied.append(source.name)
            checksums[source.name] = hashlib.sha256(destination.read_bytes()).hexdigest()
    metadata = {
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "game_sqpack": str(game),
        "sheets": sheets,
        "files": files,
        "copied": copied,
        "checksums": checksums,
    }
    (backup / "backup.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return backup


def restore_backup(project: Path, backup_name: str | None) -> None:
    root = project / "backups"
    candidates = sorted((item for item in root.iterdir() if item.is_dir()), reverse=True) if root.is_dir() else []
    backup = root / backup_name if backup_name else (candidates[0] if candidates else None)
    if backup is None or not (backup / "backup.json").is_file():
        raise SystemExit("Nessun backup Interpresona disponibile.")
    metadata = json.loads((backup / "backup.json").read_text(encoding="utf-8"))
    game = absolute(metadata["game_sqpack"])
    processes = running_game_processes()
    if processes:
        raise SystemExit("Chiudi il gioco/XIVLauncher prima del ripristino: " + "; ".join(processes))
    for name, expected in metadata.get("checksums", {}).items():
        source = backup / name
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise SystemExit(f"Backup non integro, ripristino annullato: {source.name}")
    for name in metadata.get("copied", []):
        source = backup / name
        destination = game / name
        if source.is_file():
            shutil.copy2(source, destination)
    print(f"Ripristino completato: {backup}")
    print("La traduzione precedente è stata rimossa dai file SQPACK inclusi nel backup.")


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "Interpresona-Installer/2", "Cache-Control": "no-cache", "Pragma": "no-cache"})
    try:
        with urllib.request.urlopen(request, timeout=30, context=_https_context()) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Impossibile leggere il server di distribuzione: {exc}")
    if not isinstance(data, dict):
        raise SystemExit("Risposta del server non valida.")
    return data


def _https_context() -> ssl.SSLContext:
    """Usa i certificati del sistema e, se disponibili, quelli di certifi.

    Alcune distribuzioni Linux e alcuni bundle PyInstaller non espongono a
    Python lo stesso archivio CA usato dal browser. Aggiungere certifi al
    contesto di sistema mantiene la verifica HTTPS attiva e rende il client
    indipendente dalla configurazione locale dei certificati.
    """
    context = ssl.create_default_context()
    bundled_ca = RESOURCE_DIR / "certifi-ca.pem"
    if bundled_ca.is_file():
        try:
            context.load_verify_locations(cafile=str(bundled_ca))
        except (OSError, ssl.SSLError):
            pass
    if certifi is not None:
        try:
            context.load_verify_locations(cafile=certifi.where())
        except (OSError, ssl.SSLError):
            pass
    return context


def safe_zip_member(name: str) -> str:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or ".." in Path(normalized).parts:
        raise SystemExit(f"Percorso non sicuro nel pacchetto: {name}")
    if not normalized or normalized.endswith("/"):
        raise SystemExit(f"Elemento non valido nel pacchetto: {name}")
    return normalized


def _notify(progress, fraction: float, message: str) -> None:
    if progress is not None:
        progress(max(0.0, min(1.0, fraction)), message)


def download_archive(url: str, expected_hash: str, directory: Path, label: str, progress=None) -> Path:
    archive = directory / f"{label}.zip"
    request = urllib.request.Request(url, headers={"User-Agent": "Interpresona-Installer/3", "Cache-Control": "no-cache", "Pragma": "no-cache"})
    try:
        with urllib.request.urlopen(request, timeout=120, context=_https_context()) as response, archive.open("wb") as output:
            total = int(response.headers.get("Content-Length", "0") or 0)
            copied = 0
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                output.write(block)
                copied += len(block)
                _notify(progress, (copied / total) * 0.82 if total else 0.35, f"Download {label}: {copied / 1024 / 1024:.1f} MB" + (f" / {total / 1024 / 1024:.1f} MB" if total else ""))
    except (OSError, urllib.error.URLError) as exc:
        raise SystemExit(f"Download {label} fallito: {exc}")
    _notify(progress, 0.88, f"Verifica checksum {label}…")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest.lower() != expected_hash.lower():
        raise SystemExit(f"Checksum {label} non corrispondente: atteso {expected_hash}, ricevuto {digest}")
    _notify(progress, 1.0, f"Download {label} verificato")
    return archive


def update_csv_from_server(config: dict, manifest: dict, progress=None) -> dict:
    """Compatibility fallback for servers that have not published EXD yet."""
    _, workspace, _ = project_paths(config)
    api = str(config.get("distribution_api", DEFAULT_API)).rstrip("/")
    package = manifest.get("zip_package") or {}
    download = api_url(api, str(package.get("download_url") or "/api/v1/download/latest"))
    expected_hash = str(package.get("sha256", "")).lower()
    expected_files = {str(item.get("path") or item.get("filename")) for item in manifest.get("files", [])}
    expected_files.discard("None")
    if not expected_hash or not expected_files:
        raise SystemExit("Manifest remoto privo di checksum o file installabili.")
    workspace.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="interpresona-update-") as tmp:
        archive = download_archive(download, expected_hash, Path(tmp), "translation", progress)
        try:
            with zipfile.ZipFile(archive) as bundle:
                members = [safe_zip_member(item) for item in bundle.namelist()]
                actual_files = {item for item in members if item.lower().endswith((".csv", ".json"))}
                missing = sorted(expected_files - actual_files)
                if missing:
                    raise SystemExit("Il pacchetto non contiene tutti i file dichiarati: " + ", ".join(missing[:8]))
                staged = Path(tmp) / "staged"
                for member in members:
                    source = bundle.extract(member, staged)
                    destination = workspace / member
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
        except zipfile.BadZipFile as exc:
            raise SystemExit(f"Archivio aggiornamento non valido: {exc}")
    print(f"Aggiornamento CSV scaricato: {len(expected_files)} file")
    return manifest


def update_exd_from_server(config: dict, manifest: dict, progress=None) -> dict:
    project, _, compiled, game = configure_engine(config)
    check_game(game)
    api = str(config.get("distribution_api", DEFAULT_API)).rstrip("/")
    package = manifest.get("exd_package") or {}
    download = api_url(api, str(package.get("download_url") or "/api/v1/download/latest-exd"))
    expected_hash = str(package.get("sha256", "")).lower()
    if not expected_hash:
        raise SystemExit("Manifest EXD privo di checksum.")
    # Il manifest e il pacchetto devono provenire dalla stessa release anche
    # se un reverse proxy conserva una risposta precedente nella cache.
    separator = "&" if "?" in download else "?"
    download = f"{download}{separator}sha256={expected_hash}"

    with tempfile.TemporaryDirectory(prefix="interpresona-exd-update-") as tmp_name:
        tmp = Path(tmp_name)
        archive = download_archive(download, expected_hash, tmp, "EXD", progress)
        try:
            with zipfile.ZipFile(archive) as bundle:
                names = {safe_zip_member(name) for name in bundle.namelist()}
                if "exd-manifest.json" not in names:
                    raise SystemExit("Pacchetto EXD privo di exd-manifest.json.")
                release = json.loads(bundle.read("exd-manifest.json").decode("utf-8"))
                if release.get("version") != manifest.get("version") or release.get("game_patch") != manifest.get("game_patch"):
                    raise SystemExit("Versione o patch del pacchetto EXD non corrispondente al manifest.")
                sheets = release.get("sheets")
                if not isinstance(sheets, dict) or not sheets:
                    raise SystemExit("Manifest EXD senza sheet installabili.")
                staged = tmp / "staged"
                for sheet, metadata in sheets.items():
                    if not isinstance(sheet, str) or not sheet or not isinstance(metadata, dict):
                        raise SystemExit("Manifest EXD non valido.")
                    files = metadata.get("files", [])
                    hashes = metadata.get("sha256", {})
                    if not isinstance(files, list) or not files:
                        raise SystemExit(f"Manifest EXD senza file per {sheet}.")
                    for file_name in files:
                        member = safe_zip_member(f"exd/{file_name}")
                        if member not in names:
                            raise SystemExit(f"EXD mancante nel pacchetto: {file_name}")
                        data = bundle.read(member)
                        expected_file_hash = str(hashes.get(file_name, "")).lower()
                        if not expected_file_hash or hashlib.sha256(data).hexdigest() != expected_file_hash:
                            raise SystemExit(f"Checksum EXD non corrispondente: {file_name}")
                        destination = staged / file_name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(data)

        except (zipfile.BadZipFile, json.JSONDecodeError) as exc:
            raise SystemExit(f"Pacchetto EXD non valido: {exc}")

        _notify(progress, 0.92, "Preparo i file EXD…")
        compiled.mkdir(parents=True, exist_ok=True)
        for sheet, metadata in release["sheets"].items():
            files = [str(item) for item in metadata["files"]]
            for file_name in files:
                source = staged / file_name
                if engine._index_entry(file_name) is None:
                    raise SystemExit(f"EXD non compatibile con l'indice locale: {file_name}")
                shutil.copy2(source, compiled / file_name)
            (compiled / f"{sheet}.manifest.json").write_text(json.dumps({"files": files}, indent=2) + "\n", encoding="utf-8")
        installed = dict(release)
        installed["installed_at"] = dt.datetime.now().isoformat(timespec="seconds")
        installed["source_manifest"] = {key: manifest.get(key) for key in ("version", "game_patch", "build_id", "last_updated")}
        (compiled / INSTALLED_RELEASE_FILENAME).write_text(json.dumps(installed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _notify(progress, 1.0, f"Release EXD pronta: {len(release['sheets'])} sheet")
    print(f"Release EXD scaricata: {len(release['sheets'])} sheet, patch {manifest.get('game_patch', 'n/d')}")
    return manifest


def update_from_server(config: dict, progress=None) -> dict:
    api = str(config.get("distribution_api", DEFAULT_API)).rstrip("/")
    manifest = fetch_json(f"{api}/manifest")
    if manifest.get("exd_package"):
        return update_exd_from_server(config, manifest, progress)
    print("Il server non pubblica ancora EXD precompilati; uso il fallback CSV.")
    return update_csv_from_server(config, manifest, progress)


def show_update_status(config: dict) -> None:
    project, _, compiled = project_paths(config)
    api = str(config.get("distribution_api", DEFAULT_API)).rstrip("/")
    remote = fetch_json(f"{api}/manifest")
    local = installed_release(compiled)
    remote_id = (remote.get("build_id"), remote.get("version"))
    local_source = local.get("source_manifest", local)
    local_id = (local_source.get("build_id"), local_source.get("version"))
    print(json.dumps({
        "project": str(project),
        "remote_version": remote.get("version"),
        "remote_patch": remote.get("game_patch"),
        "remote_build_id": remote.get("build_id"),
        "installed_version": local_source.get("version"),
        "installed_build_id": local_source.get("build_id"),
        "update_available": remote_id != local_id,
        "latest_backup": str(latest_backup(project)) if latest_backup(project) else "",
    }, indent=2, ensure_ascii=False))


def compile_sources(sheets: list[str], source: str, workspace: Path, compiled: Path) -> None:
    if source != "csv":
        return
    for sheet in sheets:
        csv_path = workspace / f"{sheet}.csv"
        if not csv_path.is_file():
            raise SystemExit(f"CSV mancante: {csv_path}")
        result = engine.compile_exd(sheet)
        if "error" in result:
            raise SystemExit(f"Compilazione {sheet}: {result['error']}")
        print(f"  compilato {sheet}: {result.get('pages', '?')} pagine")


def install(args: argparse.Namespace, config: dict, config_path: Path, progress=None) -> None:
    target_config = dict(config)
    if args.target == "test":
        if not config.get("test_dir"):
            raise SystemExit("Nessun percorso di test configurato. Usa configure --test.")
        target_config["game_sqpack"] = config["test_dir"]
    project, workspace, compiled, game = configure_engine(target_config)
    check_game(game)
    source = args.source or config.get("translation_source", "exd")
    if source not in {"exd", "csv"}:
        raise SystemExit("--source deve essere exd oppure csv")
    if args.all and source == "exd":
        release = installed_release(compiled)
        release_names = list((release.get("sheets") or {}).keys())
        sheets = selected_sheets(release_names, False) if release_names else selected_sheets(None, True)
    else:
        sheets = selected_sheets(args.sheet, args.all)
    if args.all:
        available = []
        skipped = []
        for sheet in sheets:
            exists = (workspace / f"{sheet}.csv").is_file() if source == "csv" else bool(manifest_files(compiled, sheet))
            (available if exists else skipped).append(sheet)
        sheets = available
        if skipped:
            print(f"Ignorati {len(skipped)} EXH senza sorgente locale per --all.")
        if not sheets:
            raise SystemExit("Nessuna traduzione locale installabile.")
    compile_sources(sheets, source, workspace, compiled)

    files: list[str] = []
    for sheet in sheets:
        current = manifest_files(compiled, sheet)
        if not current:
            raise SystemExit(f"EXD compilati mancanti per {sheet}. Usa --source csv oppure prepara runtime/exd.")
        files.extend(current)
    files = list(dict.fromkeys(files))
    invalid = [name for name in files if engine._index_entry(name) is None]
    if invalid:
        raise SystemExit("File non presenti nell'indice SQPACK: " + ", ".join(invalid[:8]))

    processes = running_game_processes()
    if processes and not args.force:
        raise SystemExit("Chiudi il gioco/XIVLauncher prima dell'inject (usa --force solo se sei certo): " + "; ".join(processes))
    if args.dry_run:
        print(f"Dry-run completato: {len(files)} file EXD pronti per {args.target}.")
        print("Nessun backup e nessun file di gioco sono stati modificati.")
        return
    _notify(progress, 0.08, "Creo il backup di sicurezza…")
    backup = make_backup(project, game, files, sheets)
    print(f"Backup creato: {backup}")
    results = []
    _notify(progress, 0.15, f"Applico {len(sheets)} sheet EXD…")
    for index, sheet in enumerate(sheets, 1):
        result = engine.hard_inject_sqpack(sheet)
        if "error" in result:
            raise SystemExit(f"Inject {sheet}: {result['error']}\nIl backup resta disponibile per il ripristino.")
        results.append(result)
        changed = result.get("changed_pages", 0)
        print(f"  inject {sheet}: {result.get('pages', 0)} pagine, differenze byte: {changed}")
        _notify(progress, 0.15 + 0.82 * index / len(sheets), f"Applico {sheet} ({index}/{len(sheets)})")
    report = {
        "installed_at": dt.datetime.now().isoformat(timespec="seconds"),
        "backup": str(backup),
        "sheets": sheets,
        "source": source,
        "results": results,
    }
    report_path = project / "logs" / f"install-{now_stamp()}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Installazione completata. Report: {report_path}")
    _notify(progress, 1.0, "Installazione completata")
    print("Se vuoi annullare questa installazione, usa il comando restore: il backup originale è disponibile nell'applicazione.")


def main() -> int:
    if len(sys.argv) == 1:
        return interactive_setup(DEFAULT_CONFIG)
    parser = argparse.ArgumentParser(description="Installer standalone Interpresona per FFXIV")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="file di configurazione utente")
    sub = parser.add_subparsers(dest="command", required=True)

    configure = sub.add_parser("configure", help="salva i percorsi dell'installazione")
    configure.add_argument("--game", required=True, help="cartella SQPACK che contiene 0a0000.win32.index")
    configure.add_argument("--project", default=str(PROJECT_DIR), help="cartella del progetto Interpresona")
    configure.add_argument("--test", default="", help="cartella di test opzionale")

    status = sub.add_parser("status", help="controlla percorsi e file principali")
    install_parser = sub.add_parser("install", help="compila e/o inietta le traduzioni")
    install_parser.add_argument("--sheet", action="append", help="EXH da installare; ripetibile")
    install_parser.add_argument("--all", action="store_true", help="installa tutti gli EXH catalogati")
    install_parser.add_argument("--source", choices=("exd", "csv"), help="sorgente della traduzione")
    install_parser.add_argument("--target", choices=("game", "test"), default="game", help="destinazione configurata")
    install_parser.add_argument("--dry-run", action="store_true", help="verifica tutto senza creare backup o modificare SQPACK")
    install_parser.add_argument("--force", action="store_true", help="continua anche se viene trovato un processo FFXIV")

    restore = sub.add_parser("restore", help="ripristina un backup")
    restore.add_argument("--backup", help="nome della cartella backup; predefinito: l'ultimo")
    update_parser = sub.add_parser("update", help="controlla o scarica l’ultima release dal portale HTTPS")
    update_parser.add_argument("--check", action="store_true", help="mostra se è disponibile un aggiornamento senza scaricarlo")
    apply_parser = sub.add_parser("apply", help="scarica l’ultima release e la applica al gioco")
    apply_parser.add_argument("--target", choices=("game", "test"), default="game", help="destinazione configurata")
    apply_parser.add_argument("--force", action="store_true", help="continua anche se viene trovato un processo FFXIV")
    apply_parser.add_argument("--dry-run", action="store_true", help="verifica senza modificare SQPACK")

    args = parser.parse_args()
    config_path = absolute(args.config)
    config = load_config(config_path)
    if args.command == "configure":
        config.update({"game_sqpack": str(resolve_game_path(args.game)), "project_dir": str(absolute(args.project)), "test_dir": str(resolve_game_path(args.test)) if args.test else ""})
        save_config(config_path, config)
        print(f"Configurazione salvata in {config_path}")
        print(json.dumps(config, indent=2, ensure_ascii=False))
        return 0
    if args.command == "restore":
        project, _, _ = project_paths(config)
        restore_backup(project, args.backup)
        return 0
    if args.command == "update":
        if args.check:
            show_update_status(config)
        else:
            update_from_server(config)
        return 0
    if args.command == "apply":
        update_from_server(config)
        args.command = "install"
        args.sheet = None
        args.all = True
        args.source = "exd"
        install(args, config, config_path)
        return 0
    if args.command == "status":
        project, workspace, compiled, game = configure_engine(config)
        test_dir = absolute(config["test_dir"]) if config.get("test_dir") else None
        print(json.dumps({"config": str(config_path), "game_sqpack": str(game), "game_ok": (game / "0a0000.win32.index").is_file(), "test_sqpack": str(test_dir) if test_dir else "", "test_ok": bool(test_dir and (test_dir / "0a0000.win32.index").is_file()), "project": str(project), "workspace": str(workspace), "compiled_exd": str(compiled), "csv_count": len(list(workspace.glob("*.csv"))), "compiled_count": len(list(compiled.glob("*.exd")))}, indent=2, ensure_ascii=False))
        return 0
    install(args, config, config_path)
    return 0


def interactive_setup(config_path: Path) -> int:
    """One-click setup used when the launcher is opened without arguments."""
    config = load_config(config_path)
    configured_game = resolve_game_path(config.get("game_sqpack", "")) if config.get("game_sqpack") else None
    if configured_game and (configured_game / "0a0000.win32.index").is_file():
        project = absolute(config.get("project_dir", PROJECT_DIR))
        config["game_sqpack"] = str(configured_game)
        config["project_dir"] = str(project)
        print("Interpresona — aggiornamento installato")
        print(f"Gioco: {configured_game}")
        try:
            show_update_status(config)
        except SystemExit as exc:
            print(exc)
        choice = input("Scegli: [I]nstalla aggiornamento, [R]ipristina backup, [Q]sci: ").strip().lower()
        if choice.startswith("r"):
            restore_backup(project, None)
            return 0
        if not choice.startswith("i"):
            print("Nessuna modifica eseguita.")
            return 0
        update_from_server(config)
        args = argparse.Namespace(target="game", force=False, dry_run=False, source="exd", sheet=None, all=True)
        install(args, config, config_path)
        return 0

    print("Interpresona — installazione guidata")
    print("Inserisci il percorso della cartella di FFXIV oppure della cartella SQPACK/ffxiv.")
    game_input = input("Percorso gioco: ").strip()
    if not game_input:
        print("Nessun percorso indicato.")
        return 2
    game = resolve_game_path(game_input)
    if not (game / "0a0000.win32.index").is_file():
        print(f"Non trovo i file SQPACK in: {game}")
        print("Seleziona la cartella che contiene 0a0000.win32.index.")
        return 2
    project_input = input(f"Cartella dati [{PROJECT_DIR}]: ").strip()
    project = absolute(project_input or PROJECT_DIR)
    config.update({"game_sqpack": str(game), "project_dir": str(project)})
    save_config(config_path, config)
    print(f"Percorso salvato in {config_path}")
    print("Download della release e verifica del checksum...")
    update_from_server(config)
    args = argparse.Namespace(target="game", force=False, dry_run=False, source="exd", sheet=None, all=True)
    install(args, config, config_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
