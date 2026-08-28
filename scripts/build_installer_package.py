#!/usr/bin/env python3
"""Build the public, self-contained Interpresona installer archive."""

from __future__ import annotations

import argparse
import certifi
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
FILES = (
    (ROOT / "installer" / "interpresona_installer.py", "interpresona_installer.py"),
    (ROOT / "installer" / "interpresona_gui.py", "interpresona_gui.py"),
    (ROOT / "installer" / "install.sh", "install.sh"),
    (ROOT / "installer" / "install.bat", "install.bat"),
    (ROOT / "installer" / "Interpresona-Installer.sh", "Interpresona-Installer.sh"),
    (ROOT / "installer" / "Interpresona-Installer.command", "Interpresona-Installer.command"),
    (ROOT / "installer" / "Interpresona-Installer.bat", "Interpresona-Installer.bat"),
    (ROOT / "installer" / "INIZIA-QUI.txt", "INIZIA-QUI.txt"),
    (ROOT / "installer" / "README.md", "README.md"),
    (ROOT / "installer" / "config.example.json", "config.example.json"),
    (Path(certifi.where()), "certifi-ca.pem"),
    (ROOT / "app" / "ffxiv_engine.py", "app/ffxiv_engine.py"),
    (ROOT / "app" / "ffxiv_sheets.txt", "app/ffxiv_sheets.txt"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="percorso dello ZIP da creare")
    args = parser.parse_args()
    missing = [str(source) for source, _ in FILES if not source.is_file()]
    if missing:
        raise SystemExit("File mancanti: " + ", ".join(missing))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.output, "w", ZIP_DEFLATED) as archive:
        for source, target in FILES:
            archive.write(source, target)
    print(f"Creato {args.output} con {len(FILES)} file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
