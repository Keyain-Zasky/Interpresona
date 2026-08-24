from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware
from datetime import datetime, timezone
import csv
import glob
import hashlib
import json
import os
import re
import tempfile
import uuid
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import ffxiv_engine

app = FastAPI(title="FFXIV Zero-Error Translator UI", docs_url=None, redoc_url=None, openapi_url=None)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost"],
)


def _local_browser_source(value: str) -> bool:
    if not value:
        return True
    parsed = urlsplit(value)
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


@app.middleware("http")
async def local_security(request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin", "")
        referer = request.headers.get("referer", "")
        if not _local_browser_source(origin) or (not origin and referer and not _local_browser_source(referer)):
            return JSONResponse({"detail": "Origine browser non autorizzata."}, status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    return response


class ExhRequest(BaseModel):
    exh_name: str


class BatchRequest(BaseModel):
    exh_names: list[str]


class SettingsRequest(BaseModel):
    sqpack_dir: str
    csv_source_dir: str
    workspace_dir: str
    exd_dir: str


class PublishRequest(BaseModel):
    files: list[str]
    version: str = "2.0.0"
    game_patch: str = "7.10 Dawntrail"
    admin_email: str = ""
    admin_password: str = ""


def _remote_http_detail(error: urllib.error.HTTPError, fallback: str) -> str:
    """Estrae il dettaglio JSON del portale senza esporre credenziali."""
    try:
        body = error.read().decode("utf-8", "replace")
        payload = json.loads(body)
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if detail:
            return str(detail)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    return f"{fallback} (HTTP {error.code})"


DISTRIBUTION_API = os.environ.get("INTERPRESONA_DISTRIBUTION_API", "https://ffxiv.paolozzi.me/api/v1").rstrip("/")
GLOSSARY_PATH = Path(os.environ.get(
    "INTERPRESONA_GLOSSARY_PATH",
    "/home/keyain/.gemini/config/skills/ffxiv-lore-glossary/dizionario_traduzioni.csv",
)).expanduser()
_glossary_cache = {"signature": None, "rows": []}
GLOSSARY_COLUMNS = (
    "id", "sezione", "termine_originale", "traduzione_italiana",
    "attributo_1", "attributo_2", "note", "stato",
)


def _clean_names(names):
    result = []
    for name in names:
        stem = os.path.splitext(os.path.basename(str(name).strip()))[0].lower()
        if not re.fullmatch(r"[a-z0-9_]+", stem):
            continue
        if ffxiv_engine.get_file_offset(stem + ".exh")[0] is not None and stem not in result:
            result.append(stem)
    return result


def _run_batch(names, operation):
    names = _clean_names(names)
    if not names:
        raise HTTPException(status_code=400, detail="Nessun EXH valido selezionato.")
    results = []
    for name in names:
        try:
            result = operation(name)
        except Exception as exc:
            result = {"error": str(exc)}
        results.append({"name": name, **result})
    return {"success": all("error" not in item for item in results),
            "total": len(results), "results": results}


def _load_glossary_rows():
    try:
        stat = GLOSSARY_PATH.stat()
    except OSError as exc:
        raise HTTPException(status_code=404, detail=f"Dizionario non trovato: {GLOSSARY_PATH}") from exc
    signature = (stat.st_mtime_ns, stat.st_size)
    if _glossary_cache["signature"] == signature:
        return _glossary_cache["rows"]
    rows = []
    try:
        with GLOSSARY_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = [column for column in GLOSSARY_COLUMNS if column not in (reader.fieldnames or [])]
            if missing:
                raise HTTPException(status_code=500, detail="Colonne mancanti nel dizionario: " + ", ".join(missing))
            for source_row in reader:
                row = {column: str(source_row.get(column) or "").strip() for column in GLOSSARY_COLUMNS}
                if row["termine_originale"] or row["traduzione_italiana"]:
                    rows.append(row)
    except HTTPException:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise HTTPException(status_code=500, detail=f"Dizionario non leggibile: {exc}") from exc
    _glossary_cache.update({"signature": signature, "rows": rows})
    return rows


@app.get("/api/exh_catalog")
def api_exh_catalog():
    sheets = ffxiv_engine.sheet_catalog()
    return {"files": [item["name"] for item in sheets], "sheets": sheets,
            "count": len(sheets),
            "catalog_note": "SQPACK conserva gli hash; i nomi sono verificati contro il catalogo locale.",
            "categories": sorted({item["category"] for item in sheets})}


@app.get("/api/glossary")
def api_glossary(q: str = "", section: str = "", status: str = "", limit: int = 50, offset: int = 0):
    """Ricerca in sola lettura nel dizionario CSV autorevole del glossario."""
    rows = _load_glossary_rows()
    query = q.strip().casefold()
    wanted_section = section.strip().casefold()
    wanted_status = status.strip().casefold()
    filtered = []
    for row in rows:
        if wanted_section and row["sezione"].casefold() != wanted_section:
            continue
        if wanted_status and row["stato"].casefold() != wanted_status:
            continue
        if query:
            searchable = " ".join(row[column] for column in GLOSSARY_COLUMNS).casefold()
            if query not in searchable:
                continue
        filtered.append(row)
    safe_limit = max(1, min(int(limit), 200))
    safe_offset = max(0, int(offset))
    return {
        "source": str(GLOSSARY_PATH),
        "updated_at": datetime.fromtimestamp(GLOSSARY_PATH.stat().st_mtime, tz=timezone.utc).isoformat(),
        "total": len(rows),
        "matched": len(filtered),
        "offset": safe_offset,
        "limit": safe_limit,
        "sections": sorted({row["sezione"] for row in rows}),
        "statuses": sorted({row["stato"] for row in rows}),
        "rows": filtered[safe_offset:safe_offset + safe_limit],
    }


@app.post("/api/export")
def api_export(req: ExhRequest):
    result = ffxiv_engine.export_exh(req.exh_name)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/api/export_batch")
def api_export_batch(req: BatchRequest):
    return _run_batch(req.exh_names, ffxiv_engine.export_exh)


@app.post("/api/compile")
def api_compile(req: ExhRequest):
    result = ffxiv_engine.compile_exd(req.exh_name)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/api/compile_batch")
def api_compile_batch(req: BatchRequest):
    return _run_batch(req.exh_names, ffxiv_engine.compile_exd)


@app.post("/api/hard_inject")
def api_hard_inject(req: ExhRequest):
    result = ffxiv_engine.hard_inject_sqpack(req.exh_name)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/api/hard_inject_batch")
def api_hard_inject_batch(req: BatchRequest):
    return _run_batch(req.exh_names, ffxiv_engine.hard_inject_sqpack)


def _validate_source_name(filename):
    base = os.path.basename(filename or "")
    if not re.fullmatch(r"[A-Za-z0-9_]+\.csv", base, re.IGNORECASE):
        raise HTTPException(status_code=400,
                            detail=f"Nome non valido: {base}. Usa esattamente NomeSheet.csv, senza suffissi.")
    stem = base[:-4].lower()
    if ffxiv_engine.get_file_offset(stem + ".exh")[0] is None:
        raise HTTPException(status_code=400,
                            detail=f"{stem}.csv non corrisponde a un EXH presente negli SQPACK.")
    return stem


def _build_existing_exd_archive(sheet_names, output, version, game_patch):
    """Impacchetta gli EXD già compilati dallo Studio, senza ricompilarli."""
    exd_dir = Path(ffxiv_engine.EXD_DIR)
    sheets = {}
    declared_files = set()
    for value in sheet_names:
        stem = Path(str(value)).stem.lower()
        manifest_path = exd_dir / f"{stem}.manifest.json"
        if not manifest_path.is_file():
            raise ValueError(f"EXD non compilato per {stem}.csv. Compilare il file prima della pubblicazione.")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Manifest EXD non leggibile per {stem}.csv: {exc}") from exc
        page_names = manifest.get("files")
        if not isinstance(page_names, list) or not page_names:
            raise ValueError(f"Manifest EXD vuoto per {stem}.csv.")
        hashes = {}
        for page_name in page_names:
            page_name = str(page_name)
            page_path = exd_dir / page_name
            if Path(page_name).name != page_name or not page_name.endswith(".exd") or not page_path.is_file():
                raise ValueError(f"EXD compilato mancante per {stem}.csv: {page_name}")
            if page_name in declared_files:
                raise ValueError(f"Pagina EXD duplicata nella release: {page_name}")
            declared_files.add(page_name)
            hashes[page_name] = hashlib.sha256(page_path.read_bytes()).hexdigest()
        sheets[stem] = {"files": page_names, "sha256": hashes}
    if not sheets:
        raise ValueError("Nessun EXD compilato selezionato.")
    release = {
        "format": 1,
        "version": version[:40],
        "game_patch": game_patch[:80],
        "build_id": int(datetime.now(timezone.utc).timestamp()),
        "sheets": sheets,
    }
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("exd-manifest.json", json.dumps(release, ensure_ascii=False, indent=2) + "\n")
        for page_name in declared_files:
            archive.write(exd_dir / page_name, arcname=f"exd/{page_name}")
    return release


@app.post("/api/restore_backup")
def api_restore_backup():
    import shutil
    try:
        dat0 = os.path.join(ffxiv_engine.SQPACK_DIR, "0a0000.win32.dat0")
        idx = ffxiv_engine.INDEX_PATH
        idx2 = idx.replace(".index", ".index2")
        if (os.path.exists(dat0 + ".bak") and os.path.exists(idx + ".bak")
                and os.path.exists(idx2 + ".bak")):
            shutil.copy2(dat0 + ".bak", dat0)
            shutil.copy2(idx + ".bak", idx)
            shutil.copy2(idx2 + ".bak", idx2)
            return {"success": True}
        raise HTTPException(status_code=400, detail="File di backup non trovati.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/workspace_files")
def api_workspace_files():
    files = glob.glob(os.path.join(ffxiv_engine.WORKSPACE_DIR, "*.csv"))
    names = []
    for path in files:
        stem = os.path.splitext(os.path.basename(path))[0].lower()
        if ffxiv_engine.get_file_offset(stem + ".exh")[0] is not None:
            names.append(stem)
    names.sort()
    return {"files": names}


@app.get("/api/status")
def api_status():
    settings = ffxiv_engine.settings_snapshot()
    return {"sqpack_ok": settings["sqpack_ok"],
            "runtime_ok": settings["exd_ok"],
            "csv_source_ok": settings["csv_source_ok"],
            "workspace_ok": settings["workspace_ok"],
            "exd_ok": settings["exd_ok"],
            "csv_source": ffxiv_engine.CSV_SOURCE_DIR,
            "workspace": ffxiv_engine.WORKSPACE_DIR,
            "exd": ffxiv_engine.EXD_DIR}


@app.get("/api/settings")
def api_settings():
    return ffxiv_engine.settings_snapshot()


@app.post("/api/settings")
def api_save_settings(req: SettingsRequest):
    try:
        payload = req.model_dump() if hasattr(req, "model_dump") else req.dict()
        return {"success": True, **ffxiv_engine.apply_settings(payload)}
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/import_csv_folder")
def api_import_csv_folder():
    source = ffxiv_engine.CSV_SOURCE_DIR
    if not os.path.isdir(source):
        raise HTTPException(status_code=400, detail="La cartella CSV configurata non esiste.")
    imported, errors = [], []
    for path in sorted(glob.glob(os.path.join(source, "*.csv"))):
        try:
            stem = _validate_source_name(os.path.basename(path))
            destination = os.path.join(ffxiv_engine.WORKSPACE_DIR, stem + ".csv")
            import shutil
            shutil.copy2(path, destination)
            for suffix in ("_tags.json", "_meta.json"):
                sidecar = os.path.join(source, stem + suffix)
                if os.path.isfile(sidecar):
                    shutil.copy2(sidecar, os.path.join(ffxiv_engine.WORKSPACE_DIR, stem + suffix))
            imported.append(stem)
        except HTTPException as exc:
            errors.append({"filename": os.path.basename(path), "error": exc.detail})
    return {"success": not errors, "imported": imported, "errors": errors}


@app.post("/api/publish_workspace")
def api_publish_workspace(req: PublishRequest):
    """Invia al portale solo i file scelti dall'amministratore locale."""
    names = []
    for value in req.files:
        value = str(value).strip()
        if not value.lower().endswith(".csv"):
            value += ".csv"
        try:
            stem = _validate_source_name(os.path.basename(value))
        except HTTPException as exc:
            raise HTTPException(status_code=400, detail=exc.detail)
        if stem in names:
            continue
        csv_path = os.path.join(ffxiv_engine.WORKSPACE_DIR, stem + ".csv")
        if os.path.isfile(csv_path):
            names.append(stem)
    if not names:
        raise HTTPException(status_code=400, detail="Nessun CSV valido selezionato.")
    if not req.admin_email.strip() or not req.admin_password:
        raise HTTPException(status_code=400, detail="Credenziali amministrative mancanti.")
    login_payload = json.dumps({"email": req.admin_email.strip()[:320], "password": req.admin_password}).encode("utf-8")
    login_request = urllib.request.Request(f"{DISTRIBUTION_API}/admin/login", data=login_payload, headers={"Content-Type": "application/json", "User-Agent": "Interpresona-Admin-Studio/2"}, method="POST")
    try:
        with urllib.request.urlopen(login_request, timeout=20) as response:
            admin_token = json.loads(response.read().decode("utf-8")).get("access_token", "")
    except urllib.error.HTTPError as exc:
        detail = _remote_http_detail(exc, "Accesso amministratore rifiutato dal portale")
        status = exc.code if 400 <= exc.code < 500 else 502
        raise HTTPException(status_code=status, detail=f"Portale: {detail}") from exc
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail=f"Accesso amministratore non riuscito: {exc}")
    if not admin_token:
        raise HTTPException(status_code=401, detail="Accesso amministratore non riuscito.")
    with tempfile.TemporaryDirectory(prefix="interpresona-publish-") as temporary:
        exd_archive = Path(temporary) / "ffxiv_ita_latest_exd.zip"
        try:
            _build_existing_exd_archive(names, exd_archive, req.version, req.game_patch)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            raise HTTPException(status_code=400, detail=f"EXD non pronti per la pubblicazione: {exc}") from exc

        boundary = "----Interpresona" + uuid.uuid4().hex
        chunks = []
        def field(name, value):
            chunks.extend([f"--{boundary}\r\n".encode(), f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(), str(value).encode(), b"\r\n"])
        field("version", req.version[:40])
        field("game_patch", req.game_patch[:80])
        chunks.extend([f"--{boundary}\r\n".encode(), b'Content-Disposition: form-data; name="exd_archive"; filename="ffxiv_ita_latest_exd.zip"\r\nContent-Type: application/zip\r\n\r\n', exd_archive.read_bytes(), b"\r\n"])
        chunks.append(f"--{boundary}--\r\n".encode())
        request = urllib.request.Request(f"{DISTRIBUTION_API}/admin/publish", data=b"".join(chunks), headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Authorization": f"Bearer {admin_token}", "User-Agent": "Interpresona-Admin-Studio/2"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = _remote_http_detail(exc, "Pubblicazione rifiutata dal portale")
            status = exc.code if 400 <= exc.code < 500 else 502
            raise HTTPException(status_code=status, detail=f"Portale: {detail}") from exc
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=502, detail=f"Pubblicazione non riuscita: {exc}")
    return {"success": True, **result}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
