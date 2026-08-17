from fastapi import FastAPI, HTTPException, UploadFile, File, Header
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import glob
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone

import ffxiv_engine

app = FastAPI(title="FFXIV Zero-Error Translator UI")


class ExhRequest(BaseModel):
    exh_name: str


class BatchRequest(BaseModel):
    exh_names: list[str]


class SettingsRequest(BaseModel):
    game_dir: str
    project_dir: str
    test_dir: str


class IssueRequest(BaseModel):
    title: str
    description: str
    category: str = "Altro"
    contact: str = ""


class IssueStatusRequest(BaseModel):
    status: str


class IssueReplyRequest(BaseModel):
    message: str


def _issue_db():
    os.makedirs(os.path.dirname(ffxiv_engine.ISSUES_DB), exist_ok=True)
    connection = sqlite3.connect(ffxiv_engine.ISSUES_DB)
    connection.row_factory = sqlite3.Row
    connection.execute("""CREATE TABLE IF NOT EXISTS issues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        category TEXT NOT NULL,
        contact TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open',
        replies TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    connection.commit()
    return connection


def _issue_dict(row, private=False):
    result = dict(row)
    result["replies"] = json.loads(result.get("replies") or "[]")
    if not private:
        result.pop("contact", None)
    return result


def _require_admin(admin_token):
    configured = os.environ.get("FFXIV_ADMIN_TOKEN", "").strip()
    # Local development remains manageable without a token. Any deployment
    # exposed beyond localhost must configure FFXIV_ADMIN_TOKEN.
    if configured and not secrets.compare_digest(admin_token or "", configured):
        raise HTTPException(status_code=403, detail="Token amministrativo non valido.")
    if not configured and os.environ.get("FFXIV_PUBLIC_DEPLOYMENT") == "1":
        raise HTTPException(status_code=503, detail="Configurare FFXIV_ADMIN_TOKEN prima di esporre il backend online.")


@app.post("/api/issues")
def api_create_issue(req: IssueRequest):
    title, description = req.title.strip(), req.description.strip()
    if not title or not description:
        raise HTTPException(status_code=400, detail="Titolo e descrizione sono obbligatori.")
    if len(title) > 160 or len(description) > 12000 or len(req.contact) > 240:
        raise HTTPException(status_code=400, detail="La segnalazione supera la lunghezza consentita.")
    now = datetime.now(timezone.utc).isoformat()
    with _issue_db() as db:
        cursor = db.execute("INSERT INTO issues(title, description, category, contact, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                            (title, description, req.category.strip()[:60] or "Altro", req.contact.strip(), now, now))
        row = db.execute("SELECT * FROM issues WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return {"success": True, "issue": _issue_dict(row)}


@app.get("/api/issues")
def api_list_issues(status: str = "", admin_token: str | None = Header(default=None, alias="X-Admin-Token")):
    private = isinstance(admin_token, str) and bool(admin_token)
    if private:
        _require_admin(admin_token)
    query = "SELECT * FROM issues"
    args = []
    if status:
        query += " WHERE status = ?"
        args.append(status)
    query += " ORDER BY updated_at DESC"
    with _issue_db() as db:
        rows = db.execute(query, args).fetchall()
    return {"issues": [_issue_dict(row, private=private) for row in rows], "admin": private}


@app.get("/api/issues/{issue_id}")
def api_get_issue(issue_id: int, admin_token: str | None = Header(default=None, alias="X-Admin-Token")):
    private = isinstance(admin_token, str) and bool(admin_token)
    if private:
        _require_admin(admin_token)
    with _issue_db() as db:
        row = db.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Segnalazione non trovata.")
    return {"issue": _issue_dict(row, private=private), "admin": private}


@app.patch("/api/issues/{issue_id}/status")
def api_update_issue_status(issue_id: int, req: IssueStatusRequest,
                            admin_token: str | None = Header(default=None, alias="X-Admin-Token")):
    _require_admin(admin_token)
    if req.status not in {"open", "in_progress", "resolved", "closed"}:
        raise HTTPException(status_code=400, detail="Stato non valido.")
    now = datetime.now(timezone.utc).isoformat()
    with _issue_db() as db:
        cursor = db.execute("UPDATE issues SET status = ?, updated_at = ? WHERE id = ?", (req.status, now, issue_id))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Segnalazione non trovata.")
        row = db.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    return {"success": True, "issue": _issue_dict(row, private=True)}


@app.post("/api/issues/{issue_id}/replies")
def api_reply_issue(issue_id: int, req: IssueReplyRequest,
                    admin_token: str | None = Header(default=None, alias="X-Admin-Token")):
    _require_admin(admin_token)
    message = req.message.strip()
    if not message or len(message) > 12000:
        raise HTTPException(status_code=400, detail="La risposta è vuota o supera la lunghezza consentita.")
    now = datetime.now(timezone.utc).isoformat()
    with _issue_db() as db:
        row = db.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Segnalazione non trovata.")
        replies = json.loads(row["replies"] or "[]")
        replies.append({"message": message, "created_at": now, "author": "admin"})
        db.execute("UPDATE issues SET replies = ?, status = 'in_progress', updated_at = ? WHERE id = ?",
                   (json.dumps(replies, ensure_ascii=False), now, issue_id))
        row = db.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    return {"success": True, "issue": _issue_dict(row, private=True)}


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


@app.get("/api/exh_catalog")
def api_exh_catalog():
    sheets = ffxiv_engine.sheet_catalog()
    return {"files": [item["name"] for item in sheets], "sheets": sheets,
            "count": len(sheets),
            "catalog_note": "SQPACK conserva gli hash; i nomi sono verificati contro il catalogo locale.",
            "categories": sorted({item["category"] for item in sheets})}


@app.post("/api/export")
def api_export(req: ExhRequest):
    result = ffxiv_engine.export_exh(req.exh_name)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/api/export_batch")
def api_export_batch(req: BatchRequest):
    output_dir = ffxiv_engine.new_history_dir("export")
    return {**_run_batch(req.exh_names, lambda name: ffxiv_engine.export_exh(name, output_dir)),
            "history_dir": output_dir}


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


def _validate_upload_name(filename):
    base = os.path.basename(filename or "")
    if not re.fullmatch(r"[A-Za-z0-9_]+\.csv", base, re.IGNORECASE):
        raise HTTPException(status_code=400,
                            detail=f"Nome non valido: {base}. Usa esattamente NomeSheet.csv, senza suffissi.")
    stem = base[:-4].lower()
    if ffxiv_engine.get_file_offset(stem + ".exh")[0] is None:
        raise HTTPException(status_code=400,
                            detail=f"{stem}.csv non corrisponde a un EXH presente negli SQPACK.")
    if stem not in _valid_workspace_stems():
        raise HTTPException(status_code=400,
                            detail=f"{stem}.csv non è un foglio testuale valido per il workspace.")
    return stem


def _valid_workspace_stems():
    """Only exact, text-bearing EXH names are allowed in the work list."""
    return {sheet["name"] for sheet in ffxiv_engine.sheet_catalog()}


def _store_uploaded_csv(stem, content, history_dir):
    audit = ffxiv_engine.csv_byte_audit(stem, content)
    with open(os.path.join(history_dir, stem + ".csv"), "wb") as output:
        output.write(content)
    with open(os.path.join(ffxiv_engine.WORKSPACE_DIR, stem + ".csv"), "wb") as output:
        output.write(content)
    return audit


@app.post("/api/upload_csv")
async def api_upload_csv(file: UploadFile = File(...)):
    stem = _validate_upload_name(file.filename)
    ffxiv_engine.snapshot_current_data()
    history_dir = ffxiv_engine.new_history_dir("import")
    content = await file.read()
    audit = _store_uploaded_csv(stem, content, history_dir)
    return {"success": True, "filename": stem + ".csv", "sheet": stem,
            "history_dir": history_dir, "byte_audit": [audit]}


@app.post("/api/upload_csv_batch")
async def api_upload_csv_batch(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="Nessun CSV ricevuto.")
    ffxiv_engine.snapshot_current_data()
    history_dir = ffxiv_engine.new_history_dir("import")
    uploaded, errors, byte_audit = [], [], []
    for file in files:
        try:
            stem = _validate_upload_name(file.filename)
            content = await file.read()
            byte_audit.append({"sheet": stem, **_store_uploaded_csv(stem, content, history_dir)})
            uploaded.append(stem)
        except HTTPException as exc:
            errors.append({"filename": file.filename, "error": exc.detail})
    return {"success": not errors, "uploaded": uploaded, "errors": errors,
            "history_dir": history_dir, "byte_audit": byte_audit}


@app.post("/api/restore_backup")
def api_restore_backup():
    import shutil
    try:
        dat0 = os.path.join(ffxiv_engine.SQPACK_DIR, "0a0000.win32.dat0")
        idx = ffxiv_engine.INDEX_PATH
        idx2 = idx.replace(".index", ".index2")
        backup_dir = ffxiv_engine.BACKUP_SQPACK_DIR
        sources = [(dat0, os.path.join(backup_dir, "0a0000.win32.dat0.bak")),
                   (idx, os.path.join(backup_dir, "0a0000.win32.index.bak")),
                   (idx2, os.path.join(backup_dir, "0a0000.win32.index2.bak"))]
        if all(os.path.exists(source) for _, source in sources):
            for destination, source in sources:
                shutil.copy2(source, destination)
            return {"success": True}
        raise HTTPException(status_code=400, detail="Backup del progetto non trovati. Eseguire prima un inject o copiare i backup nella cartella del progetto.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/workspace_files")
def api_workspace_files():
    files = glob.glob(os.path.join(ffxiv_engine.WORKSPACE_DIR, "*.csv"))
    valid_stems = _valid_workspace_stems()
    names = []
    for path in files:
        stem = os.path.splitext(os.path.basename(path))[0].lower()
        if re.fullmatch(r"[a-z0-9_]+", stem) and stem in valid_stems:
            names.append(stem)
    names.sort()
    return {"files": names}


@app.get("/api/status")
def api_status():
    settings = ffxiv_engine.settings_snapshot()
    return {"sqpack_ok": settings["sqpack_ok"],
            "runtime_ok": settings["exd_ok"],
            "test_ok": settings["test_ok"],
            "workspace_ok": settings["workspace_ok"],
            "exd_ok": settings["exd_ok"],
            "workspace": ffxiv_engine.WORKSPACE_DIR,
            "exd": ffxiv_engine.EXD_DIR,
            "export": ffxiv_engine.EXPORT_DIR,
            "history": settings["history"]}


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
    ffxiv_engine.snapshot_current_data()
    history_dir = ffxiv_engine.new_history_dir("import")
    imported, errors, byte_audit = [], [], []
    for path in sorted(glob.glob(os.path.join(source, "*.csv"))):
        try:
            stem = _validate_upload_name(os.path.basename(path))
            destination = os.path.join(ffxiv_engine.WORKSPACE_DIR, stem + ".csv")
            import shutil
            with open(path, "rb") as source_file:
                content = source_file.read()
            byte_audit.append({"sheet": stem, **ffxiv_engine.csv_byte_audit(stem, content)})
            shutil.copy2(path, os.path.join(history_dir, stem + ".csv"))
            shutil.copy2(path, destination)
            for suffix in ("_tags.json", "_meta.json"):
                sidecar = os.path.join(source, stem + suffix)
                if os.path.isfile(sidecar):
                    shutil.copy2(sidecar, os.path.join(history_dir, stem + suffix))
                    shutil.copy2(sidecar, os.path.join(ffxiv_engine.WORKSPACE_DIR, stem + suffix))
            imported.append(stem)
        except HTTPException as exc:
            errors.append({"filename": os.path.basename(path), "error": exc.detail})
    return {"success": not errors, "imported": imported, "errors": errors,
            "history_dir": history_dir, "byte_audit": byte_audit}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
