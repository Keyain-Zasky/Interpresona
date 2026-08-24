#!/usr/bin/env python3
"""Build a native GUI executable with PyInstaller on the current platform."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--work", type=Path, default=ROOT / ".build" / "pyinstaller")
    parser.add_argument("--package", type=Path, help="crea anche lo ZIP nativo indicato")
    args = parser.parse_args()
    pyinstaller = shutil.which("pyinstaller") or str(Path(sys.executable).with_name("pyinstaller"))
    if not Path(pyinstaller).is_file() and not shutil.which("pyinstaller"):
        raise SystemExit("PyInstaller non trovato. Installa i requisiti con: python -m pip install -r packaging/requirements-build.txt")
    args.dist.mkdir(parents=True, exist_ok=True)
    args.work.mkdir(parents=True, exist_ok=True)
    separator = os.pathsep
    command = [
        pyinstaller,
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--name", "Interpresona",
        "--paths", str(ROOT / "app"),
        "--distpath", str(args.dist),
        "--workpath", str(args.work),
        "--specpath", str(args.work),
        "--add-data", f"{ROOT / 'app' / 'ffxiv_sheets.txt'}{separator}app",
        str(ROOT / "installer" / "interpresona_gui.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    if args.package:
        executable_name = "Interpresona.exe" if platform.system().lower() == "windows" else "Interpresona"
        executable = args.dist / executable_name
        if not executable.is_file():
            raise SystemExit(f"Eseguibile PyInstaller mancante: {executable}")
        args.package.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(args.package, "w", ZIP_DEFLATED) as archive:
            archive.write(executable, executable_name)
            archive.write(ROOT / "packaging" / "native-INIZIA-QUI.txt", "INIZIA-QUI.txt")
        print(f"Creato pacchetto nativo {args.package}")
    print(f"Creato eseguibile nativo in {args.dist}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
