#!/usr/bin/env python3
"""Smoke test non distruttivo per il portale pubblico Interpresona.

Uso:
    python scripts/portal_smoke.py
    python scripts/portal_smoke.py --base-url https://ffxiv.paolozzi.me
"""

from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zipfile import ZipFile


PUBLIC_ROUTES = ("/", "/installer", "/status", "/about", "/support", "/privacy", "/cookies", "/terms")
PROTECTED_ROUTES = (
    "/api/v1/admin/users",
    "/api/v1/admin/tickets",
    "/api/v1/admin/compliance",
    "/api/v1/auth/me",
    "/api/v1/auth/export",
    "/api/v1/support/mine",
)


def request(base_url: str, path: str, *, method: str = "GET", headers: dict[str, str] | None = None, data: bytes | None = None):
    return urlopen(
        Request(base_url.rstrip("/") + path, data=data, method=method, headers=headers or {"User-Agent": "Interpresona-portal-smoke/1.0"}),
        timeout=15,
    )


def expect_status(base_url: str, path: str, expected: int, *, method: str = "GET", headers: dict[str, str] | None = None, data: bytes | None = None):
    try:
        response = request(base_url, path, method=method, headers=headers, data=data)
        actual = response.status
        body = response.read().decode("utf-8", "replace")
    except HTTPError as error:
        actual = error.code
        body = error.read().decode("utf-8", "replace")
    if actual != expected:
        raise AssertionError(f"{path}: atteso HTTP {expected}, ricevuto {actual} ({body[:160]})")
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://ffxiv.paolozzi.me")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    for path in PUBLIC_ROUTES:
        body = expect_status(base_url, path, 200)
        if path == "/" and "Interpresona" not in body:
            raise AssertionError("La home non contiene il brand previsto.")
    security_txt = expect_status(base_url, "/.well-known/security.txt", 200)
    if "Contact: mailto:" not in security_txt or "Canonical: https://" not in security_txt:
        raise AssertionError("security.txt non contiene i campi obbligatori.")

    installer = expect_status(base_url, "/installer", 200)
    if "Installa la traduzione." not in installer or "Download gestito dall’installer" not in installer:
        raise AssertionError("La pagina installer non contiene il percorso operativo previsto.")
    with request(base_url, "/api/v1/download/installer") as installer_response:
        installer_archive = installer_response.read()
    try:
        with ZipFile(BytesIO(installer_archive)) as archive:
            members = set(archive.namelist())
            if "app/ffxiv_engine.py" not in members or "app/ffxiv_sheets.txt" not in members:
                raise AssertionError("Il pacchetto installer non contiene il motore o il catalogo EXH.")
            if archive.testzip() is not None:
                raise AssertionError("Il pacchetto installer contiene un file corrotto.")
    except Exception as error:
        if isinstance(error, AssertionError):
            raise
        raise AssertionError(f"Il pacchetto installer non è uno ZIP valido: {error}") from error
    version = json.loads(request(base_url, "/api/v1/version").read().decode("utf-8"))
    for platform_name, package in (version.get("installer_packages") or {}).items():
        package_url = package.get("download_url")
        if not package_url or not package.get("sha256"):
            raise AssertionError(f"Metadati incompleti per installer {platform_name}.")
        with request(base_url, package_url) as native_response:
            native_archive = native_response.read()
        if hashlib.sha256(native_archive).hexdigest() != package["sha256"]:
            raise AssertionError(f"Checksum installer non corrispondente: {platform_name}.")
        with ZipFile(BytesIO(native_archive)) as archive:
            if archive.testzip() is not None:
                raise AssertionError(f"Pacchetto nativo corrotto: {platform_name}.")
    if not version.get("installer_version"):
        raise AssertionError("Versione installer mancante.")
    manifest = json.loads(request(base_url, "/api/v1/manifest").read().decode("utf-8"))
    exd_package = manifest.get("exd_package") or {}
    if not exd_package.get("sha256") or not exd_package.get("download_url"):
        raise AssertionError("Il manifest non pubblica il pacchetto EXD precompilato.")
    with request(base_url, "/api/v1/download/latest-exd") as exd_response:
        exd_archive = exd_response.read()
    if __import__("hashlib").sha256(exd_archive).hexdigest() != exd_package["sha256"]:
        raise AssertionError("Checksum del pacchetto EXD non corrispondente al manifest.")
    try:
        with ZipFile(BytesIO(exd_archive)) as archive:
            release = json.loads(archive.read("exd-manifest.json").decode("utf-8"))
            if not release.get("sheets") or archive.testzip() is not None:
                raise AssertionError("Il pacchetto EXD non contiene una release valida.")
    except Exception as error:
        if isinstance(error, AssertionError):
            raise
        raise AssertionError(f"Il pacchetto EXD non è valido: {error}") from error
    cookies = expect_status(base_url, "/cookies", 200)
    if "interpresona_session" not in cookies or "token temporanei" in cookies:
        raise AssertionError("La pagina Cookie contiene una descrizione non aggiornata.")
    admin = expect_status(base_url, "/admin", 200)
    for marker in ("AREA AMMINISTRATIVA", "confirmLegalReviewButton", "case 'toggle-user'", "userSearch", "userStatus", "ticketSearch", "ticketCategoryFilter"):
        if marker not in admin:
            raise AssertionError(f"L’area admin non contiene: {marker}")
    if "sessionStorage" in admin:
        raise AssertionError("L’area admin persiste ancora token nel browser.")
    if "style=" in admin:
        raise AssertionError("L’area admin usa ancora stili inline.")
    if admin.count("const adminEmail") != 1:
        raise AssertionError("Lo script admin contiene dichiarazioni duplicate.")
    support = expect_status(base_url, "/support", 200)
    if "sessionStorage.setItem" in support:
        raise AssertionError("La pagina supporto persiste ancora token nel browser.")
    if "style=" in support:
        raise AssertionError("La pagina supporto usa ancora stili inline.")
    if "sendTicketButton" not in support or "registerButton" not in support:
        raise AssertionError("La pagina supporto non espone invio anonimo e creazione account.")
    if "Perché questa pausa?" in support or "assistenza verrà riattivata" in support:
        raise AssertionError("La pagina supporto contiene ancora il testo di sospensione precedente.")
    robots = expect_status(base_url, "/robots.txt", 200)
    if "/admin" not in robots or "/api/" not in robots:
        raise AssertionError("robots.txt non protegge le aree non indicizzabili.")
    sitemap = expect_status(base_url, "/sitemap.xml", 200)
    if "https://ffxiv.paolozzi.me/installer" not in sitemap:
        raise AssertionError("Sitemap incompleta.")

    home_response = request(base_url, "/")
    home = home_response.read().decode("utf-8", "replace")
    if "FFXIV in italiano" not in home or "sessionStorage" in home or "style=" in home:
        raise AssertionError("La home non contiene la nuova presentazione o conserva token nel browser.")
    if 'property="og:title"' not in home or 'rel="canonical"' not in home:
        raise AssertionError("Metadati Open Graph o canonical mancanti.")
    csp = home_response.headers.get("Content-Security-Policy", "")
    if home_response.headers.get("Server"):
        raise AssertionError("L’header Server è ancora esposto.")
    if "max-age=31536000" not in home_response.headers.get("Strict-Transport-Security", ""):
        raise AssertionError("HSTS non presente.")
    style_nonces = re.findall(r'<style nonce="([^"]+)"', home)
    script_nonces = re.findall(r'<script nonce="([^"]+)"', home)
    if not style_nonces or not script_nonces or not all(f"'nonce-{nonce}" in csp for nonce in style_nonces + script_nonces):
        raise AssertionError("Nonce CSP mancanti o non coerenti.")
    for directive in ("object-src 'none'", "frame-ancestors 'none'", "script-src-attr 'none'"):
        if directive not in csp:
            raise AssertionError(f"Direttiva CSP mancante: {directive}")
    if "style-src-attr" in csp:
        raise AssertionError("La CSP consente ancora stili inline.")

    for path in PROTECTED_ROUTES:
        expect_status(base_url, path, 401)
    expect_status(base_url, "/api/v1/download/example.csv", 410)
    expect_status(base_url, "/api/v1/upload", 410, method="POST")
    expect_status(base_url, "/api/v1/auth/logout", 403, method="POST", headers={"Cookie": "interpresona_session=fake"})
    expect_status(base_url, "/api/v1/auth/logout", 403, method="POST", headers={"Origin": "https://evil.example"})
    oversized_body = b"0" * (2 * 1024 * 1024 + 1)
    expect_status(base_url, "/api/v1/auth/logout", 413, method="POST", data=oversized_body, headers={"Content-Type": "application/octet-stream", "Origin": "https://ffxiv.paolozzi.me"})

    print(f"Portal smoke test OK: {base_url}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, URLError) as error:
        print(f"Portal smoke test FAILED: {error}", file=sys.stderr)
        raise SystemExit(1)
