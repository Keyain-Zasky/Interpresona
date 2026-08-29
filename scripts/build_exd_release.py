#!/usr/bin/env python3
"""Compile the current server CSV release into an EXD installer package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API = "https://ffxiv.paolozzi.me/api/v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_member(name: str) -> str:
    normalized = name.replace("\\", "/")
    if not normalized or normalized.startswith("/") or ".." in Path(normalized).parts:
        raise SystemExit(f"Membro ZIP non sicuro: {name}")
    return normalized


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Interpresona-EXD-Builder/1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def overlay_file(root: Path, sheet: str, suffix: str) -> Path | None:
    """Find a selected local CSV/sidecar without depending on case."""
    wanted = f"{sheet}{suffix}".lower()
    exact = root / f"{sheet}{suffix}"
    if exact.is_file():
        return exact
    for candidate in root.iterdir():
        if candidate.is_file() and candidate.name.lower() == wanted:
            return candidate
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="ZIP EXD da creare")
    parser.add_argument("--source", default=f"{DEFAULT_API}/download/latest", help="ZIP CSV della release sorgente")
    parser.add_argument("--manifest", default=f"{DEFAULT_API}/manifest", help="manifest della release sorgente")
    parser.add_argument("--sqpack", default="/home/keyain/Games/Steam/FINAL FANTASY XIV Online/game/sqpack/ffxiv", help="SQPACK originale per la compilazione")
    parser.add_argument("--overlay-dir", type=Path, help="cartella locale con i CSV selezionati da sovrapporre alla release")
    parser.add_argument("--overlay-sheet", action="append", default=[], help="sheet locale da sovrapporre; ripetibile")
    parser.add_argument("--version", help="versione da scrivere nel manifest EXD")
    parser.add_argument("--game-patch", help="patch da scrivere nel manifest EXD")
    args = parser.parse_args()

    source_manifest = json.loads(fetch(args.manifest).decode("utf-8"))
    source_zip = fetch(args.source)
    with tempfile.TemporaryDirectory(prefix="interpresona-exd-build-") as temp_name:
        temp = Path(temp_name)
        workspace = temp / "workspace"
        runtime = temp / "runtime"
        compiled = temp / "exd"
        workspace.mkdir()
        runtime.mkdir()
        compiled.mkdir()
        with zipfile.ZipFile(__import__("io").BytesIO(source_zip)) as archive:
            for member in archive.namelist():
                normalized = safe_member(member)
                if normalized.endswith((".csv", "_tags.json", "_meta.json")):
                    destination = workspace / normalized
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(member))

        overlay_sheets = [Path(item).stem.lower() for item in args.overlay_sheet]
        if args.overlay_dir and overlay_sheets:
            for sheet in dict.fromkeys(overlay_sheets):
                csv_source = overlay_file(args.overlay_dir, sheet, ".csv")
                if csv_source is None:
                    raise SystemExit(f"CSV locale mancante per overlay: {sheet}.csv")
                shutil.copy2(csv_source, workspace / f"{sheet}.csv")
                for suffix in ("_tags.json", "_meta.json"):
                    sidecar = overlay_file(args.overlay_dir, sheet, suffix)
                    if sidecar is not None:
                        shutil.copy2(sidecar, workspace / f"{sheet}{suffix}")

        os.environ["INTERPRESONA_ENGINE_PROJECT_DIR"] = str(temp)
        os.environ["INTERPRESONA_ENGINE_RUNTIME_DIR"] = str(runtime)
        os.environ["INTERPRESONA_ENGINE_CATALOG_FILE"] = str(ROOT / "app" / "ffxiv_sheets.txt")
        sys.path.insert(0, str(ROOT / "app"))
        import ffxiv_engine as engine

        engine.USER_SETTINGS_PATH = str(temp / "settings.json")
        engine.RUNTIME_SETTINGS_PATH = str(runtime / "settings.json")
        engine.apply_settings({
            "sqpack_dir": args.sqpack,
            "csv_source_dir": str(workspace),
            "workspace_dir": str(workspace),
            "exd_dir": str(compiled),
        })
        available = {item["name"] for item in engine.sheet_catalog()}
        requested = [str(item.get("sheet", "")).lower() for item in source_manifest.get("files", [])]
        requested.extend(overlay_sheets)
        invalid_overlay = sorted(set(overlay_sheets) - available)
        if invalid_overlay:
            raise SystemExit("Overlay non compilabile con il catalogo EXH locale: " + ", ".join(invalid_overlay))
        sheets = [sheet for sheet in requested if sheet in available and (workspace / f"{sheet}.csv").is_file()]
        if not sheets:
            raise SystemExit("Nessun CSV della release è compilabile con il catalogo EXH locale.")

        skipped = sorted(set(requested) - set(sheets))
        if skipped:
            print("Sorgenti descrittive non convertibili in EXD ignorate: " + ", ".join(skipped))
        release_sheets = {}
        for sheet in dict.fromkeys(sheets):
            result = engine.compile_exd(sheet)
            if "error" in result:
                raise SystemExit(f"Compilazione {sheet}: {result['error']}")
            files = []
            hashes = {}
            for name in result.get("files", []):
                source = compiled / name
                if not source.is_file() or engine._index_entry(name) is None:
                    raise SystemExit(f"EXD non installabile o non presente nell'indice: {name}")
                files.append(name)
                hashes[name] = sha256(source)
            release_sheets[sheet] = {"files": files, "sha256": hashes}
            print(f"  {sheet}: {len(files)} EXD")

        args.output.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "format": 1,
            "version": args.version or source_manifest.get("version"),
            "game_patch": args.game_patch or source_manifest.get("game_patch"),
            "game_version": source_manifest.get("game_version") or engine.game_version(),
            "build_id": source_manifest.get("build_id"),
            "sheets": release_sheets,
        }
        with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("exd-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            for sheet in release_sheets.values():
                for name in sheet["files"]:
                    archive.write(compiled / name, arcname=f"exd/{name}")
    print(f"Creato {args.output}: {len(release_sheets)} sheet EXD")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
