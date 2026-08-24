import os
import json
import time
import zipfile
import hashlib
import csv
import shutil
import tempfile
import secrets
import uuid
import sqlite3
import re
from ipaddress import ip_address
from collections import defaultdict, deque
from html import escape
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, Header
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel

BASE_DIR = Path("/opt/ffxiv-portal")
DATA_DIR = BASE_DIR / "data"
TRANSLATIONS_DIR = DATA_DIR / "translations"
ARCHIVES_DIR = DATA_DIR / "archives"
EXD_ARCHIVE = ARCHIVES_DIR / "ffxiv_ita_latest_exd.zip"
MANIFEST_FILE = DATA_DIR / "manifest.json"
RELEASE_META_FILE = DATA_DIR / "release.json"
PROGRESS_FILE = DATA_DIR / "progress.json"
INSTALLER_PACKAGE = DATA_DIR / "interpresona-installer.zip"
INSTALLER_PACKAGES_DIR = DATA_DIR / "installers"
INSTALLER_PACKAGES_META = DATA_DIR / "installer-packages.json"
INSTALLER_VERSION = os.environ.get("FFXIV_INSTALLER_VERSION", "0.4.0")
INSTALLER_PLATFORMS = {
    "linux-x86_64": "Interpresona-linux-x86_64.zip",
    "windows-x86_64": "Interpresona-windows-x86_64.zip",
    "macos-x86_64": "Interpresona-macos-x86_64.zip",
    "macos-arm64": "Interpresona-macos-arm64.zip",
}
LEGAL_SETTINGS_FILE = DATA_DIR / "legal-settings.json"
DATABASE_FILE = DATA_DIR / "portal.sqlite3"
CONTACT_EMAIL = os.environ.get("FFXIV_CONTACT_EMAIL", "paolozz325@gmail.com")
TICKET_RETENTION_DAYS = 365
IP_RETENTION_DAYS = 30
PRIVACY_NOTICE_VERSION = "2026-08-24"
SESSION_COOKIE_NAME = "interpresona_session"
MAX_PASSWORD_LENGTH = 256
MAX_EMAIL_LENGTH = 320
ALLOWED_TICKET_CATEGORIES = {
    "Generale",
    "Installer",
    "Inject",
    "Crash",
    "Traduzione",
    "Privacy / GDPR",
}

DONATION_WIDGET = """<span class="donation-widget" data-bmc-widget><a href="https://buymeacoffee.com/keyain" target="_blank" rel="noopener">☕ Donazione volontaria</a></span>"""

COOKIE_CONSENT = """<div id="privacy-consent" class="consent-banner" role="dialog" aria-labelledby="privacy-consent-title" aria-live="polite" hidden><div><strong id="privacy-consent-title">La tua privacy, prima di tutto.</strong><p>Questo sito usa solo il necessario. Il widget Buy Me a Coffee è un servizio esterno e viene caricato soltanto se lo abiliti. <a href="/cookies">Scopri di più</a></p></div><div class="consent-actions"><button type="button" data-consent="necessary">Solo necessarie</button><button type="button" class="consent-primary" data-consent="external">Abilita servizi esterni</button></div></div><script>
(function(){
  const key='interpresona_privacy_choice';
  const version='2026-08-24';
  const maxAge=180*24*60*60*1000;
  function readChoice(){try{const saved=JSON.parse(localStorage.getItem(key)||'null');if(saved&&saved.version===version&&saved.choice&&(Date.now()-saved.savedAt)<maxAge)return saved.choice;}catch(error){}return '';}
  function loadExternal(){
    document.querySelectorAll('[data-bmc-widget]').forEach(function(host){
      if(host.dataset.loaded)return;
      host.dataset.loaded='1';
      const script=document.createElement('script');
      script.type='text/javascript';
      script.src='https://cdnjs.buymeacoffee.com/1.0.0/button.prod.min.js';
      [['data-name','bmc-button'],['data-slug','keyain'],['data-color','#FFDD00'],['data-emoji',''],['data-font','Cookie'],['data-text','Buy me a coffee'],['data-outline-color','#000000'],['data-font-color','#000000'],['data-coffee-color','#ffffff']].forEach(function(pair){script.setAttribute(pair[0],pair[1]);});
      host.appendChild(script);
    });
  }
  function closeBanner(){const banner=document.getElementById('privacy-consent');if(banner)banner.hidden=true;}
  function setChoice(choice){localStorage.setItem(key,JSON.stringify({choice:choice,version:version,savedAt:Date.now()}));closeBanner();if(choice==='external')loadExternal();}
  document.addEventListener('DOMContentLoaded',function(){
    const choice=readChoice();
    const banner=document.getElementById('privacy-consent');
    const header=document.querySelector('.site-header'),anchor=document.querySelector('.hero')||header;if(anchor&&banner)anchor.insertAdjacentElement('afterend',banner);
    if(!choice&&banner)banner.hidden=false;
    if(choice==='external')loadExternal();
    document.querySelectorAll('[data-consent]').forEach(function(button){button.addEventListener('click',function(){setChoice(button.dataset.consent);});});const resetButton=document.getElementById('resetPrivacyButton');if(resetButton)resetButton.addEventListener('click',function(){window.InterpresonaPrivacy.reset();});
  });
  window.InterpresonaPrivacy={reset:function(){localStorage.removeItem(key);location.reload();}};
})();
</script>"""

# API Token for uploading/syncing updates
API_SECRET_TOKEN = os.environ.get("FFXIV_API_TOKEN") or os.environ.get("FFXIV_ADMIN_TOKEN")

TRANSLATIONS_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVES_DIR.mkdir(parents=True, exist_ok=True)
INSTALLER_PACKAGES_DIR.mkdir(parents=True, exist_ok=True)


def db_connection():
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    try:
        connection.execute("PRAGMA trusted_schema = OFF")
    except sqlite3.DatabaseError:
        pass
    return connection


def init_database():
    with db_connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            must_change_password INTEGER NOT NULL DEFAULT 0,
            disabled INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS tickets (
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            email TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            status TEXT NOT NULL,
            subject TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            app_version TEXT NOT NULL,
            game_patch TEXT NOT NULL,
            logs TEXT NOT NULL,
            response TEXT NOT NULL,
            client_ip TEXT,
            consent_at TEXT,
            privacy_notice_version TEXT
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            actor_user_id INTEGER,
            actor_type TEXT NOT NULL,
            action TEXT NOT NULL,
            target TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(actor_user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at);
        """)
        for statement in (
            "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE tickets ADD COLUMN consent_at TEXT",
            "ALTER TABLE tickets ADD COLUMN privacy_notice_version TEXT",
        ):
            try:
                db.execute(statement)
            except sqlite3.OperationalError:
                pass


init_database()


def purge_expired_personal_data() -> None:
    now = datetime.now(timezone.utc)
    ip_cutoff = (now - timedelta(days=IP_RETENTION_DAYS)).isoformat()
    ticket_cutoff = (now - timedelta(days=TICKET_RETENTION_DAYS)).isoformat()
    with db_connection() as db:
        db.execute("UPDATE tickets SET client_ip=NULL WHERE client_ip IS NOT NULL AND created_at<?", (ip_cutoff,))
        db.execute("DELETE FROM tickets WHERE updated_at<? AND status IN ('resolved','closed')", (ticket_cutoff,))
        db.execute("DELETE FROM audit_log WHERE created_at<?", (ticket_cutoff,))
        db.execute("DELETE FROM sessions WHERE CAST(expires_at AS REAL)<=?", (now.timestamp(),))


purge_expired_personal_data()
try:
    os.chmod(DATABASE_FILE, 0o600)
except OSError:
    pass

app = FastAPI(
    title="Final Fantasy XIV • Italian Translation Portal & API",
    description="Piattaforma e API di distribuzione delle traduzioni italiane di Final Fantasy XIV",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[item.strip() for item in os.environ.get("FFXIV_ALLOWED_ORIGINS", "https://ffxiv.paolozzi.me").split(",") if item.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[item.strip() for item in os.environ.get("FFXIV_ALLOWED_HOSTS", "ffxiv.paolozzi.me,localhost,127.0.0.1,192.168.1.120").split(",") if item.strip()],
)

RATE_LIMIT_RULES = {
    "/api/v1/auth/login": (8, 300),
    "/api/v1/admin/login": (8, 300),
    "/api/v1/auth/register": (5, 3600),
    "/api/v1/auth/change-password": (6, 900),
    "/api/v1/admin/change-password": (6, 900),
    "/api/v1/support/tickets": (10, 600),
    "/api/v1/admin/publish": (4, 3600),
    "/api/v1/admin/installer": (12, 3600),
}
TRUSTED_PROXY_IPS = {item.strip() for item in os.environ.get("FFXIV_TRUSTED_PROXY_IPS", "192.168.1.114").split(",") if item.strip()}
MAX_RATE_LIMIT_KEYS = 10000
MAX_STANDARD_BODY_BYTES = 2 * 1024 * 1024
MAX_RELEASE_BODY_BYTES = 300 * 1024 * 1024
_rate_events = defaultdict(deque)
_last_retention_run = 0.0


def request_client_ip(request: Request) -> str:
    """Usa gli header forwarded solo quando la connessione arriva dal proxy fidato."""
    peer = request.client.host if request.client else "unknown"
    if peer in TRUSTED_PROXY_IPS:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        try:
            return str(ip_address(forwarded))
        except ValueError:
            pass
    return peer


@app.middleware("http")
async def security_and_rate_limit(request: Request, call_next):
    global _last_retention_run
    allowed_origins = {item.strip() for item in os.environ.get("FFXIV_ALLOWED_ORIGINS", "https://ffxiv.paolozzi.me").split(",") if item.strip()}
    origin = request.headers.get("origin")
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError:
            return JSONResponse({"detail": "Content-Length non valido."}, status_code=400)
        body_limit = MAX_RELEASE_BODY_BYTES if request.url.path in {"/api/v1/admin/publish", "/api/v1/admin/installer"} else MAX_STANDARD_BODY_BYTES
        if declared_length > body_limit:
            return JSONResponse({"detail": "La richiesta è troppo grande."}, status_code=413, headers={"Retry-After": "0"})
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        # Le richieste autenticate dal browser usano cookie SameSite=Lax: per
        # chiudere anche il caso di una richiesta senza Origin, richiediamo un
        # Origin esplicito e appartenente al portale. I client con Bearer/API
        # key non dipendono da questa protezione CSRF.
        if cookie_token and (not origin or origin not in allowed_origins):
            return JSONResponse({"detail": "Origine non autorizzata."}, status_code=403)
        if origin and origin not in allowed_origins:
            return JSONResponse({"detail": "Origine non autorizzata."}, status_code=403)
    authorization = request.headers.get("authorization", "")
    if cookie_token and not token_from_authorization(authorization):
        request.scope["headers"] = [
            (name, value) for name, value in request.scope["headers"] if name.lower() != b"authorization"
        ] + [(b"authorization", f"Bearer {cookie_token}".encode("ascii"))]
    retention_now = time.monotonic()
    if retention_now - _last_retention_run >= 3600:
        try:
            purge_expired_personal_data()
        except (OSError, sqlite3.Error):
            pass
        _last_retention_run = retention_now
    rule = RATE_LIMIT_RULES.get(request.url.path)
    if rule:
        limit, window = rule
        key = (request_client_ip(request), request.url.path)
        now = time.monotonic()
        if len(_rate_events) >= MAX_RATE_LIMIT_KEYS and key not in _rate_events:
            stale_before = now - max(window for _, window in RATE_LIMIT_RULES.values())
            for old_key, old_events in list(_rate_events.items()):
                if not old_events or old_events[-1] < stale_before:
                    _rate_events.pop(old_key, None)
            if len(_rate_events) >= MAX_RATE_LIMIT_KEYS:
                response = JSONResponse({"detail": "Troppe richieste. Riprova più tardi."}, status_code=429)
                response.headers["Retry-After"] = str(window)
                return response
        events = _rate_events[key]
        while events and now - events[0] > window:
            events.popleft()
        if len(events) >= limit:
            response = JSONResponse({"detail": "Troppe richieste. Riprova più tardi."}, status_code=429)
            response.headers["Retry-After"] = str(window)
            return response
        events.append(now)

    response = await call_next(request)
    is_html = response.headers.get("content-type", "").startswith("text/html")
    nonce = secrets.token_urlsafe(18) if is_html else ""
    if is_html:
        chunks = [chunk async for chunk in response.body_iterator]
        body = b"".join(chunks)
        canonical_path = escape(request.url.path or "/", quote=True)
        metadata = (
            b'<link rel="icon" href="/favicon.svg" type="image/svg+xml">'
            b'<link rel="canonical" href="https://ffxiv.paolozzi.me/' + canonical_path.lstrip("/").encode("utf-8") + b'">'
            b'<meta name="theme-color" content="#090d18">'
            b'<meta name="description" content="Interpresona: traduzione italiana di Final Fantasy XIV, distribuita tramite installer verificato.">'
            b'<meta property="og:site_name" content="Interpresona">'
            b'<meta property="og:title" content="Interpresona - FFXIV in italiano">'
            b'<meta property="og:description" content="Installer gratuito, aggiornamenti verificati e traduzione italiana per FFXIV.">'
            b'<meta property="og:type" content="website">'
            b'<meta property="og:locale" content="it_IT">'
            b'<meta name="twitter:card" content="summary">'
            b'<style nonce="' + nonce.encode("ascii") + b'">.skip-link{position:absolute;left:-9999px;top:10px;z-index:50;padding:10px 14px;border-radius:8px;background:#f3f6fb;color:#07101b;font-weight:800}.skip-link:focus{left:10px}</style>'
        )
        if b"<main>" in body:
            body = body.replace(b"<body>", b'<body><a class="skip-link" href="#main-content">Vai al contenuto</a>', 1)
            body = body.replace(b"<main>", b'<main id="main-content">', 1)
        body = body.replace(
            '<span class="brand-mark">✦</span>'.encode("utf-8"),
            b'<span class="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24" width="18" height="18" focusable="false"><path d="M12 2.5 14.4 9.6 21.5 12l-7.1 2.4L12 21.5l-2.4-7.1L2.5 12l7.1-2.4Z" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="12" cy="12" r="2.2" fill="currentColor"/></svg></span>',
            1,
        )
        body = body.replace(b"<head>", b"<head>" + metadata, 1)
        body = re.sub(rb"<script(?![^>]*\bnonce=)", b'<script nonce="' + nonce.encode("ascii") + b'"', body)
        body = re.sub(rb"<style(?![^>]*\bnonce=)", b'<style nonce="' + nonce.encode("ascii") + b'"', body)
        rebuilt = HTMLResponse(content=body, status_code=response.status_code)
        for key, value in response.headers.items():
            if key.lower() not in {"content-length", "content-type"}:
                rebuilt.headers[key] = value
        response = rebuilt
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    if request.url.path in {"/api/v1/manifest", "/api/v1/version", "/api/v1/download/latest-exd"}:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    script_policy = "'self' https://cdnjs.buymeacoffee.com https://buymeacoffee.com https://*.buymeacoffee.com"
    if nonce:
        script_policy += f" 'nonce-{nonce}'"
    style_policy = "'self'" + (f" 'nonce-{nonce}'" if nonce else "")
    response.headers.setdefault("Content-Security-Policy", f"default-src 'self'; script-src {script_policy}; style-src {style_policy}; img-src 'self' data: https://buymeacoffee.com https://*.buymeacoffee.com; connect-src 'self' https://buymeacoffee.com https://*.buymeacoffee.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    if is_html:
        response.headers.setdefault("Cache-Control", "no-store")
    response.headers["Content-Security-Policy"] = response.headers["Content-Security-Policy"].replace("frame-ancestors 'none';", "object-src 'none'; frame-src https://buymeacoffee.com https://*.buymeacoffee.com; script-src-attr 'none'; frame-ancestors 'none';")
    response.headers.setdefault("X-DNS-Prefetch-Control", "off")
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path == "/admin" or request.url.path.startswith("/api/"):
        response.headers.setdefault("X-Robots-Tag", "noindex, nofollow, noarchive")
    if request.url.path.startswith("/api/v1/auth/") or request.url.path.startswith("/api/v1/admin/") or request.url.path.startswith("/api/v1/support/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response

def compute_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_json(path: Path, value: dict) -> None:
    """Scrive un JSON tramite file temporaneo e sostituzione atomica."""
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def installer_package_metadata(platform_name: str, path: Path) -> dict:
    """Metadati pubblici di un pacchetto nativo già validato."""
    versions = _read_json_file(INSTALLER_PACKAGES_META)
    version = str(versions.get(platform_name) or INSTALLER_VERSION)
    return {
        "platform": platform_name,
        "version": version,
        "name": path.name,
        "size_bytes": path.stat().st_size,
        "size_kb": round(path.stat().st_size / 1024, 2),
        "sha256": compute_sha256(path),
        "download_url": f"/api/v1/download/installer/{platform_name}",
    }


def available_installer_packages() -> dict:
    return {
        platform_name: installer_package_metadata(platform_name, INSTALLER_PACKAGES_DIR / filename)
        for platform_name, filename in INSTALLER_PLATFORMS.items()
        if (INSTALLER_PACKAGES_DIR / filename).is_file()
    }


def require_admin(x_api_key: Optional[str]) -> None:
    if not API_SECRET_TOKEN or not x_api_key or not secrets.compare_digest(x_api_key, API_SECRET_TOKEN):
        raise HTTPException(status_code=401, detail="Credenziali amministrative non valide.")


def password_digest(password: str, salt: bytes) -> str:
    if len(password) > MAX_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"La password non può superare {MAX_PASSWORD_LENGTH} caratteri.")
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1).hex()


def validate_password(password: str) -> None:
    if len(password) < 12 or not any(character.isdigit() for character in password):
        raise HTTPException(status_code=400, detail="La password deve contenere almeno 12 caratteri e un numero.")


def normalize_email(value: str, *, optional: bool = False) -> str:
    email = str(value or "").strip().lower()
    if optional and not email:
        return ""
    if len(email) > MAX_EMAIL_LENGTH or email.count("@") != 1 or email.startswith("@") or email.endswith("@") or "." not in email.rsplit("@", 1)[1]:
        detail = "Inserisci un indirizzo email valido oppure lascia il campo vuoto." if optional else "Inserisci un indirizzo email valido."
        raise HTTPException(status_code=400, detail=detail)
    return email


def normalize_optional_email(value: str) -> str:
    return normalize_email(value, optional=True)


_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [^-]+ PRIVATE KEY-----[\s\S]*?-----END [^-]+ PRIVATE KEY-----",
    re.IGNORECASE,
)
_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[ _-]?key)\b\s*[:=]\s*[^\s,;]+"
)
_BEARER_PATTERN = re.compile(r"(?i)(\bbearer\s+)[^\s,;]+")
_KNOWN_TOKEN_PATTERN = re.compile(r"\b(?:ghp_|github_pat_|sk-)[A-Za-z0-9_\-]{12,}")


def sanitize_ticket_logs(value: str) -> str:
    """Riduce il rischio che un utente archivi credenziali dentro un log."""
    text = str(value or "").strip()[:30000]
    text = _PRIVATE_KEY_PATTERN.sub("[REDACTED PRIVATE KEY]", text)
    text = _BEARER_PATTERN.sub(r"\1[REDACTED]", text)
    text = _SECRET_VALUE_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    return _KNOWN_TOKEN_PATTERN.sub("[REDACTED TOKEN]", text)


def issue_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).timestamp()
    with db_connection() as db:
        user = db.execute("SELECT is_admin FROM users WHERE id=?", (user_id,)).fetchone()
        max_age = 60 * 60 * 8 if user and int(user["is_admin"]) else 60 * 60 * 24 * 30
        db.execute("DELETE FROM sessions WHERE CAST(expires_at AS REAL)<=?", (now,))
        expires = now + max_age
        db.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user_id, str(expires)))
    return token


def session_max_age(is_admin: bool) -> int:
    return 60 * 60 * 8 if is_admin else 60 * 60 * 24 * 30


def set_session_cookie(response: JSONResponse, token: str, is_admin: bool) -> JSONResponse:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=session_max_age(is_admin),
        httponly=True,
        secure=not bool(os.environ.get("FFXIV_DISABLE_SECURE_COOKIES")),
        samesite="lax",
        path="/",
    )
    return response


def token_from_authorization(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        return ""
    return authorization[7:].strip()


def current_user(authorization: Optional[str]) -> Optional[sqlite3.Row]:
    token = token_from_authorization(authorization)
    if not token:
        return None
    with db_connection() as db:
        row = db.execute("SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id WHERE sessions.token_hash=? AND users.disabled=0 AND CAST(sessions.expires_at AS REAL)>?", (hashlib.sha256(token.encode()).hexdigest(), datetime.now(timezone.utc).timestamp())).fetchone()
    return row


def require_user(authorization: Optional[str]) -> sqlite3.Row:
    user = current_user(authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="Accedi o registrati per continuare.")
    return user


def require_admin_access(
    authorization: Optional[str],
    x_api_key: Optional[str],
    *,
    allow_api_key: bool = False,
) -> sqlite3.Row | None:
    """Richiede una sessione admin; il token tecnico vale solo dove previsto."""
    if allow_api_key and API_SECRET_TOKEN and x_api_key and secrets.compare_digest(x_api_key, API_SECRET_TOKEN):
        return None
    user = current_user(authorization)
    if user is None or not int(user["is_admin"]):
        raise HTTPException(status_code=401, detail="Accesso amministratore richiesto.")
    if int(user["must_change_password"]):
        raise HTTPException(status_code=403, detail="Cambia la password temporanea prima di continuare.")
    return user


def record_admin_audit(action: str, target: str, actor: Optional[sqlite3.Row] = None, details: str = "") -> None:
    """Registra solo metadati operativi, mai credenziali o contenuti sensibili."""
    actor_id = int(actor["id"]) if actor is not None else None
    actor_type = "session" if actor is not None else "api_key"
    with db_connection() as db:
        db.execute(
            "INSERT INTO audit_log(created_at,actor_user_id,actor_type,action,target,details) VALUES(?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), actor_id, actor_type, action[:80], target[:160], details[:500]),
        )


def ticket_from_row(row: sqlite3.Row) -> dict:
    # L'indirizzo IP resta nel database solo per la retention anti-abuso; non
    # viene restituito alle interfacce web, agli export utente o all'admin UI.
    item = dict(row)
    item.pop("client_ip", None)
    return item


def release_metadata() -> dict:
    try:
        data = json.loads(RELEASE_META_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def parse_bool(value: object, default: bool = False) -> bool:
    """Interpreta in modo esplicito i booleani ricevuti da JSON o configurazione."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "si", "sì"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return default


def legal_settings() -> dict:
    defaults = {
        "legal_name": "",
        "legal_type": "",
        "address": "",
        "city": "",
        "publish_address": False,
        "contact_email": CONTACT_EMAIL,
        "vat_or_tax_id": "",
        "supervisory_authority": "Garante per la protezione dei dati personali",
        "legal_basis_account": "",
        "legal_basis_support": "",
        "legal_basis_security": "",
        "transfer_info": "",
        "legal_reviewed_at": "",
        "legal_reviewed_by": "",
        "updated_at": "",
    }
    try:
        data = json.loads(LEGAL_SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key in defaults:
                if key not in data:
                    continue
                defaults[key] = parse_bool(data[key], defaults[key]) if key == "publish_address" else str(data[key]).strip()
    except (OSError, json.JSONDecodeError):
        pass
    defaults["complete"] = bool(defaults["legal_name"] and defaults["legal_type"] and defaults["address"] and defaults["contact_email"])
    return defaults


def save_legal_settings(values: dict) -> dict:
    current = legal_settings()
    updated = {
        "legal_name": str(values.get("legal_name", "")).strip()[:200],
        "legal_type": str(values.get("legal_type", current.get("legal_type", ""))).strip()[:120],
        "address": str(values.get("address", "")).strip()[:300],
        "city": str(values.get("city", "")).strip()[:160],
        "publish_address": parse_bool(values.get("publish_address", current.get("publish_address", False)), current.get("publish_address", False)),
        "contact_email": str(values.get("contact_email", CONTACT_EMAIL)).strip()[:320],
        "vat_or_tax_id": str(values.get("vat_or_tax_id", "")).strip()[:80],
        "supervisory_authority": str(values.get("supervisory_authority", current["supervisory_authority"])).strip()[:200],
        "legal_basis_account": str(values.get("legal_basis_account", current["legal_basis_account"])).strip()[:500],
        "legal_basis_support": str(values.get("legal_basis_support", current["legal_basis_support"])).strip()[:500],
        "legal_basis_security": str(values.get("legal_basis_security", current["legal_basis_security"])).strip()[:500],
        "transfer_info": str(values.get("transfer_info", current["transfer_info"])).strip()[:1000],
        "legal_reviewed_at": "",
        "legal_reviewed_by": "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    updated["contact_email"] = normalize_email(updated["contact_email"])
    atomic_write_json(LEGAL_SETTINGS_FILE, updated)
    return legal_settings()


def compliance_snapshot() -> dict:
    legal = legal_settings()
    proxy_logs_verified = parse_bool(os.environ.get("FFXIV_PROXY_LOG_RETENTION_VERIFIED", ""))
    checks = {
        "legal_identity": {
            "label": "Identità e contatto del titolare inseriti",
            "ok": bool(legal["complete"]),
            "manual": True,
        },
        "legal_bases": {
            "label": "Basi giuridiche e trasferimenti revisionati",
            "ok": bool(legal["legal_basis_account"] and legal["legal_basis_support"] and legal["legal_basis_security"] and legal["transfer_info"]),
            "manual": True,
        },
        "retention": {
            "label": "Tempi tecnici di conservazione configurati",
            "ok": TICKET_RETENTION_DAYS > 0 and IP_RETENTION_DAYS > 0,
            "manual": True,
        },
        "security_headers": {
            "label": "Header HTTPS e protezioni browser attive",
            "ok": True,
            "manual": False,
        },
        "admin_protection": {
            "label": "Area admin protetta da autenticazione",
            "ok": True,
            "manual": False,
        },
        "external_services": {
            "label": "Servizi esterni caricati solo dopo consenso",
            "ok": True,
            "manual": False,
        },
        "reverse_proxy_retention": {
            "label": "Retention dei log del reverse proxy esterno verificata",
            "ok": proxy_logs_verified,
            "manual": True,
        },
        "manual_review": {
            "label": "Informativa e basi giuridiche revisionate dal titolare",
            "ok": bool(legal.get("legal_reviewed_at")),
            "manual": True,
        },
    }
    missing = []
    if not legal["legal_name"]:
        missing.append("Nome del titolare")
    if not legal["legal_type"]:
        missing.append("Qualifica o forma giuridica")
    if not legal["address"]:
        missing.append("Recapito del titolare nell’area amministrativa")
    if not legal["contact_email"]:
        missing.append("Contatto privacy")
    if not legal["legal_basis_account"]:
        missing.append("Base giuridica per gli account")
    if not legal["legal_basis_support"]:
        missing.append("Base giuridica per assistenza e segnalazioni")
    if not legal["legal_basis_security"]:
        missing.append("Base giuridica per la sicurezza")
    if not legal["transfer_info"]:
        missing.append("Fornitori, destinatari e trasferimenti")
    if not legal.get("legal_reviewed_at"):
        missing.append("Revisione legale umana e approvazione del titolare")
    if not proxy_logs_verified:
        missing.append("Verifica della retention dei log sul reverse proxy esterno")
    return {
        "ready": all(item["ok"] for key, item in checks.items() if key != "manual_review"),
        "publication_allowed": all(item["ok"] for item in checks.values()),
        "manual_review_required": True,
        "checks": checks,
        "missing": missing,
        "updated_at": legal.get("updated_at", ""),
    }


def personal_data_collection_allowed() -> bool:
    """Blocca nuove raccolte finché la checklist privacy non è approvata."""
    return bool(compliance_snapshot().get("publication_allowed"))


def translation_progress() -> dict:
    """Legge le percentuali pubbliche impostate dall'amministratore."""
    try:
        data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError):
        data = {}

    def bounded(value):
        try:
            return round(max(0.0, min(100.0, float(value))), 1)
        except (TypeError, ValueError):
            return 0.0

    return {
        "ai_percent": bounded(data.get("ai_percent", 0)),
        "human_percent": bounded(data.get("human_percent", 0)),
        "updated_at": str(data.get("updated_at", "")),
    }


def save_translation_progress(ai_percent: float, human_percent: float) -> dict:
    progress = {
        "ai_percent": round(max(0.0, min(100.0, float(ai_percent))), 1),
        "human_percent": round(max(0.0, min(100.0, float(human_percent))), 1),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_json(PROGRESS_FILE, progress)
    return progress

def scan_translations_and_build_manifest():
    csv_files = sorted({path.resolve() for path in TRANSLATIONS_DIR.rglob("*.csv")})
    
    files_meta = []
    total_strings = 0
    total_words = 0
    
    for f in csv_files:
        rel_path = str(f.relative_to(TRANSLATIONS_DIR))
        size = f.stat().st_size
        mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat()
        sha256 = compute_sha256(f)
        
        # Count lines & estimated strings
        lines_count = 0
        try:
            with open(f, mode="r", encoding="utf-8", errors="ignore") as csvfile:
                reader = csv.reader(csvfile)
                for row in reader:
                    lines_count += 1
                    for cell in row:
                        total_words += len(cell.split())
        except Exception:
            lines_count = 0
            
        total_strings += max(0, lines_count - 1)
        
        # Category estimation
        category = "Generale"
        lower_name = f.stem.lower()
        if "quest" in lower_name or "msq" in lower_name:
            category = "Missioni & Storia (Quest)"
        elif "action" in lower_name or "skill" in lower_name or "ability" in lower_name:
            category = "Azioni & Abilità"
        elif "item" in lower_name or "equip" in lower_name:
            category = "Oggetti & Equipaggiamento"
        elif "npc" in lower_name or "dialog" in lower_name:
            category = "Dialoghi NPC & Cutscene"
        elif "ui" in lower_name or "addon" in lower_name or "system" in lower_name:
            category = "Interfaccia & Sistema"
        elif "status" in lower_name or "buff" in lower_name:
            category = "Effetti & Status"
        elif "zone" in lower_name or "place" in lower_name or "territory" in lower_name:
            category = "Zone & Toponomastica"
            
        files_meta.append({
            "filename": f.name,
            "path": rel_path,
            "sheet": f.stem.lower(),
            "category": category,
            "size_bytes": size,
            "size_kb": round(size / 1024, 2),
            "rows_count": lines_count,
            "sha256": sha256,
            "updated_at": mtime,
        })
    
    # Build complete latest.zip
    zip_path = ARCHIVES_DIR / "ffxiv_ita_latest.zip"
    temporary_zip = ARCHIVES_DIR / f".ffxiv_ita_latest.{secrets.token_hex(8)}.tmp"
    try:
        with zipfile.ZipFile(temporary_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in csv_files:
                zf.write(f, arcname=str(f.relative_to(TRANSLATIONS_DIR)))
                for suffix in ("_tags.json", "_meta.json"):
                    sidecar = f.with_name(f.stem + suffix)
                    if sidecar.is_file():
                        zf.write(sidecar, arcname=str(sidecar.relative_to(TRANSLATIONS_DIR)))
        os.replace(temporary_zip, zip_path)
    finally:
        temporary_zip.unlink(missing_ok=True)
            
    zip_size = zip_path.stat().st_size if zip_path.exists() else 0
    zip_sha256 = compute_sha256(zip_path) if zip_path.exists() else ""
    
    current_manifest = {
        "project": "FFXIV Italian Translation Project",
        "version": release_metadata().get("version") or os.environ.get("FFXIV_RELEASE_VERSION", "2.0.0"),
        "game_patch": release_metadata().get("game_patch") or os.environ.get("FFXIV_GAME_PATCH", "7.10 Dawntrail"),
        "build_id": int(time.time()),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total_files": len(files_meta),
        "total_strings": total_strings,
        "total_words": total_words,
        "zip_package": {
            "name": "ffxiv_ita_latest.zip",
            "size_bytes": zip_size,
            "size_kb": round(zip_size / 1024, 2),
            "sha256": zip_sha256,
            "download_url": "/api/v1/download/latest"
        },
        "files": files_meta
    }
    if EXD_ARCHIVE.is_file():
        current_manifest["exd_package"] = {
            "name": EXD_ARCHIVE.name,
            "size_bytes": EXD_ARCHIVE.stat().st_size,
            "size_kb": round(EXD_ARCHIVE.stat().st_size / 1024, 2),
            "sha256": compute_sha256(EXD_ARCHIVE),
            "download_url": "/api/v1/download/latest-exd",
        }
    
    atomic_write_json(MANIFEST_FILE, current_manifest)
        
    return current_manifest

def get_manifest():
    if not MANIFEST_FILE.exists():
        return scan_translations_and_build_manifest()
    try:
        with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        if EXD_ARCHIVE.is_file():
            package = {
                "name": EXD_ARCHIVE.name,
                "size_bytes": EXD_ARCHIVE.stat().st_size,
                "size_kb": round(EXD_ARCHIVE.stat().st_size / 1024, 2),
                "sha256": compute_sha256(EXD_ARCHIVE),
                "download_url": "/api/v1/download/latest-exd",
            }
            if manifest.get("exd_package") != package:
                manifest["exd_package"] = package
                atomic_write_json(MANIFEST_FILE, manifest)
        return manifest
    except Exception:
        return scan_translations_and_build_manifest()

# -------------------------------------------------------------
# REST API ENDPOINTS (For companion client application)
# -------------------------------------------------------------

@app.get("/healthz")
def health_check():
    """Controllo minimale per reverse proxy e monitoraggio del servizio."""
    return {"status": "ok"}


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots_txt():
    return "User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /api/\nSitemap: https://ffxiv.paolozzi.me/sitemap.xml\n"


@app.get("/.well-known/security.txt", response_class=PlainTextResponse)
def security_txt():
    """Canale pubblico e minimale per segnalazioni di sicurezza responsabili."""
    return (
        "Contact: mailto:paolozz325@gmail.com\n"
        "Expires: 2027-08-24T00:00:00.000Z\n"
        "Preferred-Languages: it, en\n"
        "Canonical: https://ffxiv.paolozzi.me/.well-known/security.txt\n"
    )


@app.get("/sitemap.xml")
def sitemap_xml():
    urls = ("/", "/installer", "/status", "/about", "/support", "/privacy", "/cookies", "/terms")
    body = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>" + "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">" + "".join(f"<url><loc>https://ffxiv.paolozzi.me{path}</loc></url>" for path in urls) + "</urlset>"
    return Response(content=body, media_type="application/xml")


@app.get("/favicon.svg")
def favicon_svg():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="#090d18"/><path d="m32 9 5.7 17.3L55 32l-17.3 5.7L32 55l-5.7-17.3L9 32l17.3-5.7L32 9Z" fill="#62d6ff"/><circle cx="32" cy="32" r="7" fill="#9d8cff"/></svg>'
    return Response(content=svg, media_type="image/svg+xml")

@app.get("/api/v1/version")
def api_get_version():
    """Endpoint per verificare la versione corrente e se sono disponibili aggiornamenti."""
    m = get_manifest()
    installer_package = None
    if INSTALLER_PACKAGE.is_file():
        installer_package = {
            "name": INSTALLER_PACKAGE.name,
            "size_bytes": INSTALLER_PACKAGE.stat().st_size,
            "size_kb": round(INSTALLER_PACKAGE.stat().st_size / 1024, 2),
            "sha256": compute_sha256(INSTALLER_PACKAGE),
            "download_url": "/api/v1/download/installer",
        }
    return {
        "status": "success",
        "project": m.get("project"),
        "version": m.get("version"),
        "game_patch": m.get("game_patch"),
        "build_id": m.get("build_id"),
        "last_updated": m.get("last_updated"),
        "total_files": m.get("total_files"),
        "total_strings": m.get("total_strings"),
        "total_words": m.get("total_words"),
        "zip_package": m.get("zip_package"),
        "exd_package": m.get("exd_package"),
        "installer_version": INSTALLER_VERSION if installer_package else None,
        "installer_package": installer_package,
        "installer_packages": available_installer_packages(),
    }

@app.get("/api/v1/manifest")
def api_get_manifest():
    """Manifest tecnico per l'installer, senza link pubblici ai singoli CSV."""
    manifest = json.loads(json.dumps(get_manifest()))
    for item in manifest.get("files", []):
        item.pop("download_url", None)
    return manifest

@app.get("/api/v1/download/latest")
def api_download_latest_zip():
    """Scarica il pacchetto completo ZIP di tutte le traduzioni aggiornate."""
    zip_path = ARCHIVES_DIR / "ffxiv_ita_latest.zip"
    if not zip_path.exists():
        scan_translations_and_build_manifest()
    return FileResponse(
        path=zip_path,
        filename="ffxiv_ita_latest.zip",
        media_type="application/zip"
    )


@app.get("/api/v1/download/latest-exd")
def api_download_latest_exd():
    """Scarica il pacchetto EXD precompilato per l'installer pubblico."""
    if not EXD_ARCHIVE.is_file():
        raise HTTPException(status_code=404, detail="Pacchetto EXD non ancora pubblicato.")
    return FileResponse(
        path=EXD_ARCHIVE,
        filename=EXD_ARCHIVE.name,
        media_type="application/zip",
    )


@app.get("/api/v1/download/installer")
def api_download_installer():
    """Scarica il pacchetto standalone dell'installer pubblico."""
    if not INSTALLER_PACKAGE.is_file():
        raise HTTPException(status_code=404, detail="Pacchetto installer non ancora pubblicato.")
    return FileResponse(
        path=INSTALLER_PACKAGE,
        filename="Interpresona-Installer.zip",
        media_type="application/zip"
    )


@app.get("/api/v1/download/installer/{platform_name}")
def api_download_native_installer(platform_name: str):
    """Scarica il pacchetto nativo per la piattaforma riconosciuta dall'app."""
    filename = INSTALLER_PLATFORMS.get(platform_name)
    if not filename:
        raise HTTPException(status_code=404, detail="Piattaforma installer non supportata.")
    package = INSTALLER_PACKAGES_DIR / filename
    if not package.is_file():
        raise HTTPException(status_code=404, detail="Pacchetto nativo non ancora pubblicato per questa piattaforma.")
    return FileResponse(path=package, filename=filename, media_type="application/zip")

@app.get("/api/v1/download/{filename:path}")
def api_download_csv_file(filename: str):
    """I CSV non sono distribuiti singolarmente: li gestisce l'installer."""
    raise HTTPException(
        status_code=410,
        detail="I file CSV non sono disponibili per il download singolo. Usa l'installer ufficiale.",
    )

@app.get("/api/v1/stats")
def api_get_stats():
    """Statistiche aggregate suddivise per categoria di traduzione."""
    m = get_manifest()
    categories = {}
    for f in m.get("files", []):
        cat = f.get("category", "Generale")
        if cat not in categories:
            categories[cat] = {"count": 0, "rows": 0, "size_kb": 0}
        categories[cat]["count"] += 1
        categories[cat]["rows"] += f.get("rows_count", 0)
        categories[cat]["size_kb"] += f.get("size_kb", 0)
    return {
        "total_files": m.get("total_files"),
        "total_strings": m.get("total_strings"),
        "total_words": m.get("total_words"),
        "categories": categories
    }

@app.post("/api/v1/upload")
async def api_upload_translation(request: Request):
    """Endpoint dismesso: la pubblicazione parte esclusivamente dall'Admin Studio."""
    raise HTTPException(status_code=410, detail="Il caricamento è disponibile esclusivamente dall'Admin Studio locale.")

@app.post("/api/v1/rebuild")
def api_rebuild_manifest(x_api_key: Optional[str] = Header(None)):
    """Forza la rigenerazione del manifest e dello zip."""
    require_admin(x_api_key)
    metadata = release_metadata()
    if not EXD_ARCHIVE.is_file():
        raise HTTPException(status_code=409, detail="Impossibile rigenerare una release senza pacchetto EXD.")
    update_exd_release_metadata(EXD_ARCHIVE, str(metadata.get("version") or "2.0.0"), str(metadata.get("game_patch") or "7.10 Dawntrail"))
    m = scan_translations_and_build_manifest()
    record_admin_audit("manifest_rebuild", "current", details=f"files={m.get('total_files', 0)}")
    return {"status": "success", "manifest": m}


def validate_exd_archive(path: Path, expected_version: str, expected_patch: str) -> dict:
    """Validate the EXD release before it can become publicly active."""
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise HTTPException(status_code=400, detail="Il pacchetto EXD contiene un file corrotto.")
            names = set(archive.namelist())
            if "exd-manifest.json" not in names:
                raise HTTPException(status_code=400, detail="Pacchetto EXD privo di exd-manifest.json.")
            release = json.loads(archive.read("exd-manifest.json").decode("utf-8"))
            if release.get("version") != expected_version or release.get("game_patch") != expected_patch:
                raise HTTPException(status_code=400, detail="Versione o patch EXD non corrispondente alla release CSV.")
            sheets = release.get("sheets")
            if not isinstance(sheets, dict) or not sheets:
                raise HTTPException(status_code=400, detail="Manifest EXD senza sheet installabili.")
            declared = {"exd-manifest.json"}
            total_uncompressed = 0
            for sheet, metadata in sheets.items():
                if not isinstance(sheet, str) or not re.fullmatch(r"[a-z0-9_]+", sheet):
                    raise HTTPException(status_code=400, detail="Nome sheet EXD non valido.")
                if not isinstance(metadata, dict):
                    raise HTTPException(status_code=400, detail=f"Metadati EXD non validi per {sheet}.")
                files = metadata.get("files", [])
                hashes = metadata.get("sha256", {})
                if not isinstance(files, list) or not files or not isinstance(hashes, dict):
                    raise HTTPException(status_code=400, detail=f"Manifest EXD incompleto per {sheet}.")
                for file_name in files:
                    if not isinstance(file_name, str) or Path(file_name).name != file_name or not file_name.endswith(".exd"):
                        raise HTTPException(status_code=400, detail=f"Nome file EXD non valido: {file_name}")
                    member = f"exd/{file_name}"
                    if member not in names:
                        raise HTTPException(status_code=400, detail=f"EXD dichiarato ma assente: {file_name}")
                    data = archive.read(member)
                    expected_hash = str(hashes.get(file_name, "")).lower()
                    if not expected_hash or hashlib.sha256(data).hexdigest() != expected_hash:
                        raise HTTPException(status_code=400, detail=f"Checksum EXD non valido: {file_name}")
                    declared.add(member)
                    total_uncompressed += len(data)
            if total_uncompressed > 250 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="Il pacchetto EXD supera il limite complessivo di 250 MB.")
            unexpected = sorted(name for name in names if name not in declared)
            if unexpected:
                raise HTTPException(status_code=400, detail="Pacchetto EXD con contenuti non dichiarati.")
            return release
    except HTTPException:
        raise
    except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Pacchetto EXD non valido: {exc}")


@app.post("/api/v1/admin/publish")
async def admin_publish_release(
    files: Optional[List[UploadFile]] = File(None),
    exd_archive: Optional[UploadFile] = File(None),
    version: str = Form("2.0.0"),
    game_patch: str = Form("7.10 Dawntrail"),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    """Pubblica una release EXD validata; i CSV sono opzionali e restano privati."""
    actor = require_admin_access(authorization, x_api_key, allow_api_key=True)
    files = files or []
    release_version = version.strip()[:40]
    release_patch = game_patch.strip()[:80]
    if not release_version or not release_patch:
        raise HTTPException(status_code=400, detail="Versione e patch sono obbligatorie.")
    if exd_archive is None:
        raise HTTPException(status_code=400, detail="La release deve includere il pacchetto EXD precompilato.")
    allowed = {".csv", ".json"}
    seen_names = set()
    total_upload_bytes = 0
    with tempfile.TemporaryDirectory(prefix="interpresona-release-", dir=str(DATA_DIR)) as temporary:
        staging = Path(temporary)
        staged_names = []
        for upload in files:
            filename = Path(upload.filename or "").name
            suffix = Path(filename).suffix.lower()
            if not filename or suffix not in allowed or filename != (staging / filename).name:
                raise HTTPException(status_code=400, detail=f"File non consentito: {upload.filename}")
            if filename in seen_names:
                raise HTTPException(status_code=400, detail=f"File duplicato nella release: {filename}")
            seen_names.add(filename)
            if suffix == ".json" and not (filename.endswith("_tags.json") or filename.endswith("_meta.json")):
                raise HTTPException(status_code=400, detail=f"Sidecar non riconosciuto: {filename}")
            content = await upload.read()
            if not content or len(content) > 50 * 1024 * 1024:
                raise HTTPException(status_code=400, detail=f"File vuoto o troppo grande: {filename}")
            total_upload_bytes += len(content)
            if total_upload_bytes > 250 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="La release supera il limite complessivo di 250 MB.")
            destination = staging / filename
            destination.write_bytes(content)
            staged_names.append(filename)
        exd_filename = Path(exd_archive.filename or "").name
        if exd_filename != EXD_ARCHIVE.name:
            raise HTTPException(status_code=400, detail=f"Nome pacchetto EXD non valido: {exd_archive.filename}")
        exd_content = await exd_archive.read()
        if not exd_content or len(exd_content) > 250 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Pacchetto EXD vuoto o troppo grande.")
        staged_exd = staging / EXD_ARCHIVE.name
        staged_exd.write_bytes(exd_content)
        validate_exd_archive(staged_exd, release_version, release_patch)
        release_time = datetime.now(timezone.utc)
        old_release = None
        for offset in range(60):
            candidate = ARCHIVES_DIR / f"release-{(release_time + timedelta(seconds=offset)).strftime('%Y%m%d-%H%M%S')}"
            if not candidate.exists():
                old_release = candidate
                break
        if old_release is None:
            raise HTTPException(status_code=409, detail="Impossibile creare un identificativo release univoco.")
        old_release.mkdir(parents=True, exist_ok=True)
        for source in (MANIFEST_FILE, ARCHIVES_DIR / "ffxiv_ita_latest.zip", EXD_ARCHIVE, RELEASE_META_FILE):
            if source.is_file():
                shutil.copy2(source, old_release / source.name)
        shutil.copytree(TRANSLATIONS_DIR, old_release / "translations")
        for name in staged_names:
            shutil.copy2(staging / name, TRANSLATIONS_DIR / name)
        shutil.copy2(staged_exd, EXD_ARCHIVE)
        atomic_write_json(RELEASE_META_FILE, {"version": release_version, "game_patch": release_patch})
        manifest = scan_translations_and_build_manifest()
    record_admin_audit(
        "release_publish",
        "current",
        actor,
        details=f"version={manifest.get('version', '')};patch={manifest.get('game_patch', '')};files={len(staged_names)};exd=1",
    )
    return {"status": "success", "version": manifest.get("version"), "build_id": manifest.get("build_id"), "total_files": manifest.get("total_files"), "uploaded": staged_names, "exd_uploaded": True}


@app.post("/api/v1/admin/installer")
async def admin_publish_installer(
    installer: UploadFile = File(...),
    platform_name: str = Form(...),
    version: str = Form("0.4.0"),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    """Pubblica un pacchetto nativo verificato per una sola piattaforma."""
    actor = require_admin_access(authorization, x_api_key, allow_api_key=True)
    filename = INSTALLER_PLATFORMS.get(platform_name)
    if not filename:
        raise HTTPException(status_code=400, detail="Piattaforma installer non supportata.")
    release_version = version.strip()[:40]
    if not release_version:
        raise HTTPException(status_code=400, detail="La versione installer è obbligatoria.")
    uploaded_name = Path(installer.filename or "").name
    if uploaded_name != filename:
        raise HTTPException(status_code=400, detail=f"Nome pacchetto non valido: atteso {filename}.")
    content = await installer.read()
    if not content or len(content) > 300 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Pacchetto installer vuoto o troppo grande.")
    with tempfile.TemporaryDirectory(prefix="interpresona-installer-", dir=str(DATA_DIR)) as temporary:
        staged = Path(temporary) / filename
        staged.write_bytes(content)
        try:
            with zipfile.ZipFile(staged) as archive:
                if archive.testzip() is not None:
                    raise HTTPException(status_code=400, detail="Il pacchetto installer contiene file corrotti.")
                members = []
                for raw_name in archive.namelist():
                    safe_name = raw_name.replace("\\", "/")
                    if not safe_name or safe_name.startswith("/") or ".." in Path(safe_name).parts:
                        raise HTTPException(status_code=400, detail="Il pacchetto installer contiene un percorso non sicuro.")
                    members.append(safe_name)
                expected_executable = "Interpresona.exe" if platform_name == "windows-x86_64" else "Interpresona"
                if expected_executable not in members:
                    raise HTTPException(status_code=400, detail=f"Eseguibile mancante nel pacchetto: {expected_executable}.")
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail=f"Pacchetto installer non valido: {exc}") from exc
        destination = INSTALLER_PACKAGES_DIR / filename
        temporary_destination = INSTALLER_PACKAGES_DIR / f".{filename}.{secrets.token_hex(8)}.tmp"
        shutil.copy2(staged, temporary_destination)
        os.replace(temporary_destination, destination)
    versions = _read_json_file(INSTALLER_PACKAGES_META)
    versions[platform_name] = release_version
    atomic_write_json(INSTALLER_PACKAGES_META, versions)
    metadata = installer_package_metadata(platform_name, destination)
    record_admin_audit("installer_publish", platform_name, actor, details=f"version={release_version};sha256={metadata['sha256']}")
    return {"status": "success", "package": metadata}


class TicketCreate(BaseModel):
    subject: str
    description: str
    category: str = "Generale"
    email: str = ""
    app_version: str = ""
    game_patch: str = ""
    logs: str = ""
    privacy_consent: bool = False


class TicketUpdate(BaseModel):
    status: Optional[str] = None
    response: Optional[str] = None


class RegisterRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class AccountDeleteRequest(BaseModel):
    password: str


class UserStatusUpdate(BaseModel):
    disabled: bool


class ProgressRequest(BaseModel):
    ai_percent: float
    human_percent: float


class ReleaseUpdate(BaseModel):
    version: str
    game_patch: str


class LegalSettingsRequest(BaseModel):
    legal_name: str = ""
    legal_type: str = ""
    address: str = ""
    city: str = ""
    publish_address: bool = False
    contact_email: str = CONTACT_EMAIL
    vat_or_tax_id: str = ""
    supervisory_authority: str = "Garante per la protezione dei dati personali"
    legal_basis_account: str = ""
    legal_basis_support: str = ""
    legal_basis_security: str = ""
    transfer_info: str = ""


@app.post("/api/v1/support/tickets")
def create_support_ticket(ticket: TicketCreate, request: Request, authorization: Optional[str] = Header(None)):
    """Riceve una segnalazione anonima o associata a un account opzionale."""
    if not personal_data_collection_allowed():
        raise HTTPException(status_code=503, detail="L’invio delle segnalazioni non è disponibile in questo momento.")
    subject = ticket.subject.strip()[:160]
    description = ticket.description.strip()[:12000]
    if not subject or not description:
        raise HTTPException(status_code=400, detail="Oggetto e descrizione sono obbligatori.")
    if not ticket.privacy_consent:
        raise HTTPException(status_code=400, detail="È necessario confermare di aver letto l'informativa privacy prima di inviare la segnalazione.")
    category = ticket.category.strip()[:80]
    if category not in ALLOWED_TICKET_CATEGORIES:
        raise HTTPException(status_code=400, detail="Categoria della segnalazione non valida.")
    user = current_user(authorization)
    item = {
        "id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": "open",
        "subject": subject,
        "description": description,
        "category": category,
        "app_version": ticket.app_version.strip()[:40],
        "game_patch": ticket.game_patch.strip()[:40],
        "logs": sanitize_ticket_logs(ticket.logs),
        "response": "",
        "client_ip": request_client_ip(request),
        "consent_at": datetime.now(timezone.utc).isoformat(),
        "privacy_notice_version": PRIVACY_NOTICE_VERSION,
    }
    item["user_id"] = int(user["id"]) if user else None
    item["email"] = str(user["email"]) if user else normalize_optional_email(ticket.email)
    with db_connection() as db:
        db.execute("INSERT INTO tickets(id,user_id,email,created_at,updated_at,status,subject,description,category,app_version,game_patch,logs,response,client_ip,consent_at,privacy_notice_version) VALUES(:id,:user_id,:email,:created_at,:updated_at,:status,:subject,:description,:category,:app_version,:game_patch,:logs,:response,:client_ip,:consent_at,:privacy_notice_version)", item)
    return {"status": "success", "ticket_id": item["id"], "message": "Segnalazione ricevuta."}


@app.post("/api/v1/auth/register")
def register_account(credentials: RegisterRequest):
    if not personal_data_collection_allowed():
        raise HTTPException(status_code=503, detail="La creazione dell’account non è disponibile in questo momento.")
    email = normalize_email(credentials.email)
    validate_password(credentials.password)
    salt = secrets.token_bytes(16)
    try:
        with db_connection() as db:
            cursor = db.execute("INSERT INTO users(email,password_hash,salt,created_at) VALUES(?,?,?,?)", (email, password_digest(credentials.password, salt), salt.hex(), datetime.now(timezone.utc).isoformat()))
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Esiste già un account con questa email.")
    token = issue_session(int(user_id))
    return set_session_cookie(JSONResponse({"status": "success", "access_token": token, "email": email}), token, False)


def authenticate_account(credentials: LoginRequest) -> tuple[dict, str]:
    email = normalize_email(credentials.email)
    with db_connection() as db:
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    # Esegue sempre lo stesso KDF anche per email inesistenti o account sospesi,
    # evitando una differenza temporale facilmente osservabile durante il login.
    salt = bytes.fromhex(user["salt"]) if user is not None else b"\x00" * 16
    computed_hash = password_digest(credentials.password, salt)
    valid = user is not None and not int(user["disabled"] or 0) and secrets.compare_digest(computed_hash, user["password_hash"])
    if not valid:
        raise HTTPException(status_code=401, detail="Email o password non validi.")
    token = issue_session(int(user["id"]))
    return {"status": "success", "access_token": token, "email": email, "is_admin": bool(user["is_admin"]), "must_change_password": bool(user["must_change_password"])}, token


@app.post("/api/v1/auth/login")
def login_account(credentials: LoginRequest):
    result, token = authenticate_account(credentials)
    return set_session_cookie(JSONResponse(result), token, bool(result["is_admin"]))


@app.post("/api/v1/admin/login")
def login_admin(credentials: LoginRequest):
    result, token = authenticate_account(credentials)
    if not result.get("is_admin"):
        with db_connection() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
        raise HTTPException(status_code=403, detail="Questo account non è amministratore.")
    return set_session_cookie(JSONResponse(result), token, True)


@app.post("/api/v1/auth/change-password")
def change_account_password(credentials: PasswordChangeRequest, authorization: Optional[str] = Header(None)):
    user = require_user(authorization)
    if not secrets.compare_digest(password_digest(credentials.current_password, bytes.fromhex(user["salt"])), user["password_hash"]):
        raise HTTPException(status_code=401, detail="La password attuale non è valida.")
    validate_password(credentials.new_password)
    if credentials.current_password == credentials.new_password:
        raise HTTPException(status_code=400, detail="La nuova password deve essere diversa da quella attuale.")
    salt = secrets.token_bytes(16)
    with db_connection() as db:
        db.execute("UPDATE users SET password_hash=?,salt=? WHERE id=?", (password_digest(credentials.new_password, salt), salt.hex(), user["id"]))
        db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
    token = issue_session(int(user["id"]))
    return set_session_cookie(JSONResponse({"status": "success", "access_token": token, "message": "Password aggiornata e sessioni precedenti revocate."}), token, bool(user["is_admin"]))


@app.post("/api/v1/admin/change-password")
def change_admin_password(credentials: LoginRequest, authorization: Optional[str] = Header(None)):
    user = current_user(authorization)
    if user is None or not int(user["is_admin"]):
        raise HTTPException(status_code=401, detail="Accesso amministratore richiesto.")
    validate_password(credentials.password)
    salt = secrets.token_bytes(16)
    with db_connection() as db:
        db.execute("UPDATE users SET password_hash=?,salt=?,must_change_password=0 WHERE id=?", (password_digest(credentials.password, salt), salt.hex(), user["id"]))
        db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
    record_admin_audit("admin_password_change", f"user:{user['id']}", user)
    response = JSONResponse({"status": "success", "message": "Password amministratore aggiornata. Tutte le sessioni precedenti sono state revocate."})
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


@app.get("/api/v1/auth/me")
def account_me(authorization: Optional[str] = Header(None)):
    user = require_user(authorization)
    return {
        "id": user["id"],
        "email": user["email"],
        "created_at": user["created_at"],
        "is_admin": bool(user["is_admin"]),
        "must_change_password": bool(user["must_change_password"]),
    }


@app.post("/api/v1/auth/logout")
def account_logout(authorization: Optional[str] = Header(None)):
    token = token_from_authorization(authorization)
    if token:
        with db_connection() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
    response = JSONResponse({"status": "success"})
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


@app.get("/api/v1/auth/export")
def account_export(authorization: Optional[str] = Header(None)):
    user = require_user(authorization)
    with db_connection() as db:
        tickets = [ticket_from_row(row) for row in db.execute("SELECT * FROM tickets WHERE user_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()]
    return {"account": {"id": user["id"], "email": user["email"], "created_at": user["created_at"]}, "tickets": tickets}


@app.post("/api/v1/auth/delete")
def account_delete(credentials: AccountDeleteRequest, authorization: Optional[str] = Header(None)):
    user = require_user(authorization)
    if not secrets.compare_digest(password_digest(credentials.password, bytes.fromhex(user["salt"])), user["password_hash"]):
        raise HTTPException(status_code=401, detail="Password non valida.")
    if int(user["is_admin"]):
        with db_connection() as db:
            other_admin = db.execute("SELECT COUNT(*) FROM users WHERE is_admin=1 AND id<>?", (user["id"],)).fetchone()[0]
        if not other_admin:
            raise HTTPException(status_code=400, detail="Crea un altro amministratore prima di eliminare l'ultimo account admin.")
    with db_connection() as db:
        db.execute("DELETE FROM tickets WHERE user_id=?", (user["id"],))
        db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        db.execute("DELETE FROM users WHERE id=?", (user["id"],))
    response = JSONResponse({"status": "success", "message": "Account e dati associati eliminati."})
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


@app.get("/api/v1/support/mine")
def my_support_tickets(authorization: Optional[str] = Header(None)):
    user = require_user(authorization)
    with db_connection() as db:
        rows = db.execute("SELECT * FROM tickets WHERE user_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()
    return {"tickets": [ticket_from_row(row) for row in rows]}


@app.get("/api/v1/admin/tickets")
def list_support_tickets(
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    status: Optional[str] = None,
    category: Optional[str] = None,
    search: str = "",
):
    require_admin_access(authorization, x_api_key)
    clauses = []
    params: list[object] = []
    if status in {"open", "in_progress", "resolved", "closed"}:
        clauses.append("status=?")
        params.append(status)
    if category and category.strip() not in {"Tutte", "Tutti"}:
        clauses.append("category=?")
        params.append(category.strip()[:80])
    search_value = str(search or "").strip().lower()[:120]
    if search_value:
        clauses.append("(LOWER(subject) LIKE ? OR LOWER(description) LIKE ?)")
        params.extend((f"%{search_value}%", f"%{search_value}%"))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with db_connection() as db:
        tickets = [ticket_from_row(row) for row in db.execute(f"SELECT * FROM tickets{where} ORDER BY created_at DESC", tuple(params)).fetchall()]
    return {"tickets": tickets, "count": len(tickets), "search": search_value}


@app.get("/api/v1/progress")
def api_get_progress():
    """Restituisce le percentuali mostrate nella homepage pubblica."""
    return {"status": "success", **translation_progress()}


@app.post("/api/v1/admin/progress")
def api_save_progress(progress: ProgressRequest, x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    actor = require_admin_access(authorization, x_api_key)
    if not (0 <= progress.ai_percent <= 100 and 0 <= progress.human_percent <= 100):
        raise HTTPException(status_code=400, detail="Le percentuali devono essere comprese tra 0 e 100.")
    result = save_translation_progress(progress.ai_percent, progress.human_percent)
    record_admin_audit("translation_progress_update", "public-progress", actor, details=f"ai={result['ai_percent']};human={result['human_percent']}")
    return {"status": "success", **result}


@app.get("/api/v1/admin/users")
def admin_list_users(
    search: str = "",
    status: str = "all",
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    """Elenco amministrativo filtrabile senza password, IP o dati delle segnalazioni."""
    require_admin_access(authorization, x_api_key)
    search_value = str(search or "").strip().lower()[:120]
    status_value = status if status in {"all", "active", "suspended", "admins"} else "all"
    clauses = []
    params: list[object] = []
    if search_value:
        clauses.append("LOWER(email) LIKE ?")
        params.append(f"%{search_value}%")
    if status_value == "active":
        clauses.append("disabled=0 AND is_admin=0")
    elif status_value == "suspended":
        clauses.append("disabled=1 AND is_admin=0")
    elif status_value == "admins":
        clauses.append("is_admin=1")
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    now_timestamp = datetime.now(timezone.utc).timestamp()
    with db_connection() as db:
        rows = db.execute(
            f"SELECT u.id,u.email,u.created_at,u.is_admin,u.disabled,"
            f"(SELECT COUNT(*) FROM sessions s WHERE s.user_id=u.id AND CAST(s.expires_at AS REAL)>?) AS active_sessions,"
            f"(SELECT COUNT(*) FROM tickets t WHERE t.user_id=u.id) AS ticket_count "
            f"FROM users u{where} ORDER BY u.created_at DESC",
            (now_timestamp, *params),
        ).fetchall()
        stats = db.execute("SELECT COUNT(*) AS total, SUM(CASE WHEN is_admin=1 THEN 1 ELSE 0 END) AS admins, SUM(CASE WHEN disabled=1 THEN 1 ELSE 0 END) AS suspended FROM users").fetchone()
    return {
        "users": [dict(row) for row in rows],
        "count": len(rows),
        "stats": {"total": int(stats["total"] or 0), "admins": int(stats["admins"] or 0), "suspended": int(stats["suspended"] or 0)},
        "search": search_value,
        "status": status_value,
    }


@app.get("/api/v1/admin/audit")
def admin_audit_log(limit: int = 50, x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    """Restituisce un registro operativo senza segreti o contenuti dei ticket."""
    require_admin_access(authorization, x_api_key)
    limit = max(1, min(100, int(limit)))
    with db_connection() as db:
        rows = db.execute(
            "SELECT id,created_at,actor_user_id,actor_type,action,target,details FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"events": [dict(row) for row in rows], "count": len(rows)}


@app.delete("/api/v1/admin/users/{user_id}")
def admin_delete_user(user_id: int, x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    current = require_admin_access(authorization, x_api_key)
    with db_connection() as db:
        target = db.execute("SELECT id,email,is_admin FROM users WHERE id=?", (user_id,)).fetchone()
        if target is None:
            raise HTTPException(status_code=404, detail="Utente non trovato.")
        if int(target["is_admin"]):
            raise HTTPException(status_code=400, detail="Gli account amministrativi non possono essere cancellati da questo pannello.")
        db.execute("DELETE FROM tickets WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM users WHERE id=?", (user_id,))
    record_admin_audit("user_delete", f"user:{user_id}", current)
    return {"status": "success", "deleted_user_id": user_id}


@app.post("/api/v1/admin/users/{user_id}/revoke-sessions")
def admin_revoke_user_sessions(user_id: int, x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    """Revoca le sessioni di un utente senza cancellare i suoi dati."""
    actor = require_admin_access(authorization, x_api_key)
    with db_connection() as db:
        target = db.execute("SELECT id,is_admin FROM users WHERE id=?", (user_id,)).fetchone()
        if target is None:
            raise HTTPException(status_code=404, detail="Utente non trovato.")
        if int(target["is_admin"]):
            raise HTTPException(status_code=400, detail="Le sessioni amministrative si gestiscono dall’account admin.")
        cursor = db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        revoked = cursor.rowcount
    record_admin_audit("user_sessions_revoke", f"user:{user_id}", actor, details=f"sessions={revoked}")
    return {"status": "success", "user_id": user_id, "revoked_sessions": revoked}


@app.post("/api/v1/admin/users/{user_id}/status")
def admin_update_user_status(user_id: int, update: UserStatusUpdate, x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    actor = require_admin_access(authorization, x_api_key)
    with db_connection() as db:
        target = db.execute("SELECT id,is_admin,disabled FROM users WHERE id=?", (user_id,)).fetchone()
        if target is None:
            raise HTTPException(status_code=404, detail="Utente non trovato.")
        if int(target["is_admin"]):
            raise HTTPException(status_code=400, detail="Gli account amministrativi non possono essere sospesi da questo pannello.")
        db.execute("UPDATE users SET disabled=? WHERE id=?", (int(update.disabled), user_id))
        revoked = 0
        if update.disabled:
            revoked = db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,)).rowcount
    action = "user_disable" if update.disabled else "user_enable"
    record_admin_audit(action, f"user:{user_id}", actor, details=f"sessions_revoked={revoked}")
    return {"status": "success", "user_id": user_id, "disabled": update.disabled, "revoked_sessions": revoked}


@app.get("/api/v1/admin/legal-settings")
def admin_get_legal_settings(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    require_admin_access(authorization, x_api_key)
    return legal_settings()


@app.post("/api/v1/admin/legal-settings")
def admin_save_legal_settings(settings: LegalSettingsRequest, x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    actor = require_admin_access(authorization, x_api_key)
    values = settings.model_dump() if hasattr(settings, "model_dump") else settings.dict()
    result = save_legal_settings(values)
    record_admin_audit("legal_settings_update", "privacy-settings", actor, details=f"complete={result['complete']}")
    return {"status": "success", **result}


@app.get("/api/v1/admin/compliance")
def admin_compliance(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    require_admin_access(authorization, x_api_key)
    return compliance_snapshot()


@app.post("/api/v1/admin/compliance/confirm")
def admin_confirm_legal_review(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    """Registra una conferma esplicita del titolare dopo la revisione umana."""
    actor = require_admin_access(authorization, x_api_key)
    legal = legal_settings()
    required = (legal["legal_name"], legal["legal_type"], legal["address"], legal["contact_email"], legal["legal_basis_account"], legal["legal_basis_support"], legal["legal_basis_security"], legal["transfer_info"])
    if not all(required):
        raise HTTPException(status_code=400, detail="Completa identità, basi giuridiche e destinatari prima di confermare la revisione.")
    reviewed_at = datetime.now(timezone.utc).isoformat()
    payload = {key: value for key, value in legal.items() if key != "complete"}
    payload["legal_reviewed_at"] = reviewed_at
    payload["legal_reviewed_by"] = f"user:{actor['id']}" if actor is not None else "api-key"
    atomic_write_json(LEGAL_SETTINGS_FILE, payload)
    record_admin_audit("legal_review_confirmed", "privacy-settings", actor)
    return {"status": "success", **compliance_snapshot()}


def _read_json_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _release_summary(release_id: str, path: Optional[Path] = None, active: bool = False) -> dict:
    if active:
        manifest = get_manifest()
        metadata = release_metadata()
        return {
            "id": "current",
            "active": True,
            "version": str(manifest.get("version") or metadata.get("version") or "n/d"),
            "game_patch": str(manifest.get("game_patch") or metadata.get("game_patch") or "n/d"),
            "updated_at": str(manifest.get("last_updated", "")),
            "total_files": int(manifest.get("total_files", 0)),
        }
    manifest = _read_json_file(path / "manifest.json")
    metadata = _read_json_file(path / "release.json")
    return {
        "id": release_id,
        "active": False,
        "version": str(metadata.get("version") or manifest.get("version") or "n/d"),
        "game_patch": str(metadata.get("game_patch") or manifest.get("game_patch") or "n/d"),
        "updated_at": str(manifest.get("last_updated", "")) or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "total_files": int(manifest.get("total_files", 0)),
    }


def _archive_release_path(release_id: str) -> Path:
    if not re.fullmatch(r"release-[0-9]{8}-[0-9]{6}", release_id):
        raise HTTPException(status_code=400, detail="Identificativo release non valido.")
    path = (ARCHIVES_DIR / release_id).resolve()
    if path.parent != ARCHIVES_DIR.resolve() or not path.is_dir():
        raise HTTPException(status_code=404, detail="Release storica non trovata.")
    return path


def update_exd_release_metadata(path: Path, version: str, game_patch: str) -> None:
    """Keep the active EXD manifest aligned when only release labels change."""
    if not path.is_file():
        return
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with zipfile.ZipFile(path) as source:
            if "exd-manifest.json" not in source.namelist():
                raise HTTPException(status_code=409, detail="Il pacchetto EXD attivo non ha un manifest aggiornabile.")
            release = json.loads(source.read("exd-manifest.json").decode("utf-8"))
            release["version"] = version
            release["game_patch"] = game_patch
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as target:
                target.writestr("exd-manifest.json", json.dumps(release, ensure_ascii=False, indent=2) + "\n")
                for item in source.infolist():
                    if item.filename != "exd-manifest.json":
                        target.writestr(item.filename, source.read(item.filename))
        os.replace(temporary, path)
    except HTTPException:
        raise
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Impossibile aggiornare il manifest EXD attivo: {exc}")
    finally:
        temporary.unlink(missing_ok=True)


@app.get("/api/v1/admin/releases")
def admin_list_releases(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    require_admin_access(authorization, x_api_key)
    releases = [_release_summary("current", active=True)]
    for path in sorted(ARCHIVES_DIR.glob("release-*"), reverse=True):
        if path.is_dir() and re.fullmatch(r"release-[0-9]{8}-[0-9]{6}", path.name):
            releases.append(_release_summary(path.name, path))
    return {"releases": releases, "count": len(releases)}


@app.post("/api/v1/admin/releases/{release_id}")
def admin_update_release(release_id: str, update: ReleaseUpdate, x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    actor = require_admin_access(authorization, x_api_key)
    version = update.version.strip()[:40]
    game_patch = update.game_patch.strip()[:80]
    if not version or not game_patch:
        raise HTTPException(status_code=400, detail="Versione e patch sono obbligatorie.")
    if release_id == "current":
        update_exd_release_metadata(EXD_ARCHIVE, version, game_patch)
        atomic_write_json(RELEASE_META_FILE, {"version": version, "game_patch": game_patch})
        manifest = scan_translations_and_build_manifest()
        record_admin_audit("release_update", "current", actor, details=f"version={version};patch={game_patch}")
        return {"status": "success", "release": _release_summary("current", active=True), "build_id": manifest.get("build_id")}
    path = _archive_release_path(release_id)
    metadata = {"version": version, "game_patch": game_patch}
    atomic_write_json(path / "release.json", metadata)
    manifest_path = path / "manifest.json"
    manifest = _read_json_file(manifest_path)
    if manifest:
        manifest["version"] = version
        manifest["game_patch"] = game_patch
        atomic_write_json(manifest_path, manifest)
    record_admin_audit("release_update", release_id, actor, details=f"version={version};patch={game_patch}")
    return {"status": "success", "release": _release_summary(release_id, path)}


@app.delete("/api/v1/admin/releases/{release_id}")
def admin_delete_release(release_id: str, x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    actor = require_admin_access(authorization, x_api_key)
    if release_id == "current":
        raise HTTPException(status_code=400, detail="La release attiva non può essere cancellata. Modificala o pubblica una nuova release.")
    path = _archive_release_path(release_id)
    shutil.rmtree(path)
    record_admin_audit("release_delete", release_id, actor)
    return {"status": "success", "deleted": release_id}


@app.patch("/api/v1/admin/tickets/{ticket_id}")
def update_support_ticket(ticket_id: str, update: TicketUpdate, x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    actor = require_admin_access(authorization, x_api_key)
    if update.status is not None and update.status not in {"open", "in_progress", "resolved", "closed"}:
        raise HTTPException(status_code=400, detail="Stato ticket non valido.")
    with db_connection() as db:
        current = db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="Ticket non trovato.")
        status = update.status if update.status is not None else current["status"]
        response = update.response[:12000] if update.response is not None else current["response"]
        db.execute("UPDATE tickets SET status=?,response=?,updated_at=? WHERE id=?", (status, response, datetime.now(timezone.utc).isoformat(), ticket_id))
        item = db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
    record_admin_audit("ticket_update", f"ticket:{ticket_id}", actor, details=f"status={status}")
    return {"status": "success", "ticket": ticket_from_row(item)}


@app.get("/admin", response_class=HTMLResponse)
def admin_portal():
    """Console amministrativa: il token viene inserito solo nel browser."""
    admin_html = """<!doctype html>
<html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Interpresona Admin</title>
<style>body{font:16px/1.55 system-ui,-apple-system,Segoe UI,sans-serif;background:radial-gradient(circle at 10% 0%,#182542 0,transparent 42%),#090d18;color:#e5e7eb;max-width:1180px;margin:0 auto;padding:34px 22px 70px}h1{font-size:clamp(2.2rem,6vw,4.8rem);line-height:.95;letter-spacing:-.06em;margin:.35rem 0 1rem}h2{letter-spacing:-.03em}input,textarea,select,button{background:#0d1422;color:#e5e7eb;border:1px solid #334155;border-radius:9px;padding:.7rem;margin:.25rem}button{cursor:pointer;background:#2563eb;font-weight:700}button:hover{filter:brightness(1.1);transform:translateY(-1px)}.admin-kicker{color:#62d6ff;font-size:.75rem;font-weight:800;letter-spacing:.16em}.ticket{border:1px solid #334155;border-radius:14px;padding:1rem;margin:1rem 0;background:#111827}.muted{color:#94a3b8;font-size:.88rem}pre{white-space:pre-wrap;overflow:auto;background:#020617;padding:.75rem;border-radius:8px}.progress-panel{border:1px solid #263b58;border-radius:16px;padding:1.2rem;margin:1.25rem 0;background:linear-gradient(145deg,rgba(17,24,39,.9),rgba(15,23,42,.76));box-shadow:0 16px 45px #0003}.progress-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.progress-panel label{margin:0}.progress-panel input{width:100%;margin:.25rem 0 0}.progress-message{display:inline-block;margin-left:.5rem}.release-card{border:1px solid #334155;border-radius:12px;padding:1rem;margin:1rem 0;background:#111827}.release-card.active{border-color:#38bdf8}.release-card header{display:flex;justify-content:space-between;gap:1rem;align-items:center}.release-card .release-actions{margin-top:.65rem}.danger{background:#7f1d1d}@media(max-width:700px){.progress-grid{grid-template-columns:1fr}.release-card header{display:block}}</style></head>
<body><div class="admin-kicker">INTERPRESONA / AREA AMMINISTRATIVA</div><h1>Gestione del progetto</h1>
<p class="muted">Accedi con le credenziali amministrative. I file non vengono caricati da questa pagina: la pubblicazione avviene esclusivamente dall’Admin Studio locale.</p>
<section id="loginPanel"><label class="sr-only" for="adminEmail">Email amministratore</label><input id="adminEmail" type="email" autocomplete="username" size="28"><label class="sr-only" for="adminPassword">Password amministratore</label><input id="adminPassword" type="password" autocomplete="current-password" size="22"><button id="adminLoginButton" type="button">Accedi</button><div id="adminMessage" aria-live="polite"></div></section>
<section id="adminPanel" hidden><label class="sr-only" for="newAdminPassword">Nuova password amministratore</label><input id="newAdminPassword" type="password" aria-label="Nuova password amministratore: almeno 12 caratteri e un numero" size="30"><button id="changePasswordButton">Cambia password</button><section class="progress-panel"><h2>Avanzamento traduzione</h2><p class="muted">Imposta le percentuali mostrate in fondo alla homepage pubblica.</p><div class="progress-grid"><label>Traduzione AI (%)<input id="aiProgress" type="number" min="0" max="100" step="0.1" value="0"></label><label>Revisione umana (%)<input id="humanProgress" type="number" min="0" max="100" step="0.1" value="0"></label></div><button id="saveProgressButton">Salva avanzamento</button><span id="progressMessage" class="progress-message"></span></section><section class="progress-panel"><h2>Gestione release</h2><p class="muted">Modifica i dati della release attiva o gestisci gli snapshot storici creati durante le pubblicazioni.</p><div id="releases"><span class="muted">Accedi per caricare le release.</span></div><div id="releaseMessage" class="progress-message"></div></section><section class="progress-panel"><div class="section-heading"><div><h2>Gestione utenti</h2><p class="muted">Cerca, sospendi o revoca le sessioni senza mostrare password, IP o contenuti delle segnalazioni.</p></div><span class="section-badge">ACCESSI</span></div><div class="user-summary" id="userSummary" aria-live="polite"><span><strong id="userTotal">—</strong><small>account</small></span><span><strong id="userActive">—</strong><small>attivi</small></span><span><strong id="userSuspended">—</strong><small>sospesi</small></span></div><div class="user-toolbar"><label class="compact-field">Cerca email<input id="userSearch" type="search" autocomplete="off"></label><label class="compact-field">Mostra<select id="userStatus"><option value="all">Tutti</option><option value="active">Utenti attivi</option><option value="suspended">Sospesi</option><option value="admins">Amministratori</option></select></label><button id="loadUsersButton" type="button">Aggiorna elenco</button></div><div id="users"><span class="muted">Accedi per caricare gli utenti.</span></div><div id="userMessage" class="progress-message" aria-live="polite"></div></section><section class="progress-panel"><div class="section-heading"><div><h2>Segnalazioni</h2><p class="muted">Gestisci le richieste ricevute e rispondi direttamente dal pannello.</p></div><div class="ticket-toolbar"><button id="loadTicketsButton" type="button">Aggiorna</button><label class="compact-field"><span class="sr-only">Cerca segnalazioni</span><input id="ticketSearch" type="search" autocomplete="off"></label><label class="compact-field"><span class="sr-only">Filtra categoria</span><select id="ticketCategoryFilter"><option value="">Tutte le categorie</option><option>Generale</option><option>Installer</option><option>Inject</option><option>Crash</option><option>Traduzione</option><option>Privacy / GDPR</option></select></label><label class="compact-field"><span class="sr-only">Filtra stato</span><select id="filter"><option value="">Tutti gli stati</option><option>open</option><option>in_progress</option><option>resolved</option><option>closed</option></select></label></div></div><div id="message" aria-live="polite"></div><div id="tickets"></div></section></section>
<script>
const adminEmail=document.getElementById('adminEmail'),adminPassword=document.getElementById('adminPassword'),newAdminPassword=document.getElementById('newAdminPassword'),adminMessage=document.getElementById('adminMessage'),aiProgress=document.getElementById('aiProgress'),humanProgress=document.getElementById('humanProgress'),progressMessage=document.getElementById('progressMessage'),releaseMessage=document.getElementById('releaseMessage'),userMessage=document.getElementById('userMessage'),filter=document.getElementById('filter'),legalName=document.getElementById('legalName'),legalType=document.getElementById('legalType'),legalPublishAddress=document.getElementById('legalPublishAddress'),legalEmail=document.getElementById('legalEmail'),legalAddress=document.getElementById('legalAddress'),legalCity=document.getElementById('legalCity'),legalVat=document.getElementById('legalVat'),legalAuthority=document.getElementById('legalAuthority'),legalBasisAccount=document.getElementById('legalBasisAccount'),legalBasisSupport=document.getElementById('legalBasisSupport'),legalBasisSecurity=document.getElementById('legalBasisSecurity'),legalTransferInfo=document.getElementById('legalTransferInfo'),legalMessage=document.getElementById('legalMessage'),complianceStatus=document.getElementById('complianceStatus'),auditLog=document.getElementById('auditLog');
async function loginAdmin(){const r=await fetch('/api/v1/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:adminEmail.value,password:adminPassword.value})});const d=await r.json();if(!r.ok){adminMessage.textContent=d.detail||'Accesso fallito';return}showAdmin(d);}
function showAdmin(d){document.getElementById('adminPanel').hidden=false;adminEmail.value=d.email||adminEmail.value;adminMessage.textContent=d.must_change_password?'Password temporanea: cambiala prima di usare l’area admin.':'Accesso effettuato.';loadProgress();if(!d.must_change_password){loadReleases();loadUsers();loadTickets()}}
async function restoreAdminSession(){const r=await fetch('/api/v1/auth/me');if(!r.ok)return;const d=await r.json();if(d.is_admin){showAdmin(d);if(!d.must_change_password)setTimeout(function(){if(typeof loadLegalSettings==='function'){loadLegalSettings();loadCompliance();loadAudit()}},0)}}
function adminToken(){return ''}
async function changePassword(){const r=await fetch('/api/v1/admin/change-password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:adminEmail.value,password:newAdminPassword.value})});const d=await r.json();adminMessage.textContent=r.ok?'Password aggiornata. Accedi nuovamente.':(d.detail||'Cambio password fallito');if(r.ok){await fetch('/api/v1/auth/logout',{method:'POST'});adminPassword.value='';newAdminPassword.value=''}}
async function loadProgress(){const r=await fetch('/api/v1/progress');const d=await r.json();if(r.ok){aiProgress.value=d.ai_percent;humanProgress.value=d.human_percent}}
async function saveProgress(){const payload={ai_percent:Number(aiProgress.value),human_percent:Number(humanProgress.value)};const r=await fetch('/api/v1/admin/progress',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+adminToken()},body:JSON.stringify(payload)});const d=await r.json();progressMessage.textContent=r.ok?'Avanzamento salvato.':(d.detail||'Salvataggio fallito');progressMessage.className='progress-message '+(r.ok?'success':'error');if(r.ok){aiProgress.value=d.ai_percent;humanProgress.value=d.human_percent}}
async function loadReleases(){const r=await fetch('/api/v1/admin/releases',{headers:{Authorization:'Bearer '+adminToken()}});const d=await r.json();if(!r.ok){releaseMessage.textContent=d.detail||'Impossibile caricare le release.';return}document.getElementById('releases').innerHTML=d.releases.map(item=>{const id=esc(item.id);return `<article class="release-card ${item.active?'active':''}"><header><strong>${item.active?'Release attiva':'Snapshot storico'}</strong><span class="muted">${id} · ${esc(item.updated_at||'')}</span></header><div class="progress-grid"><label>Versione<input id="release-version-${id}" value="${esc(item.version)}"></label><label>Patch<input id="release-patch-${id}" value="${esc(item.game_patch)}"></label></div><div class="release-actions"><button data-admin-action="save-release" data-id="${id}">Salva dati</button>${item.active?'<span class="muted">La release attiva non può essere cancellata.</span>':`<button class="danger" data-admin-action="delete-release" data-id="${id}">Cancella snapshot</button>`}</div></article>`}).join('')}
async function saveRelease(id){const version=document.getElementById('release-version-'+id).value;const gamePatch=document.getElementById('release-patch-'+id).value;const r=await fetch('/api/v1/admin/releases/'+encodeURIComponent(id),{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+adminToken()},body:JSON.stringify({version,game_patch:gamePatch})});const d=await r.json();releaseMessage.textContent=r.ok?'Dati release aggiornati.':(d.detail||'Modifica fallita');releaseMessage.className='progress-message '+(r.ok?'success':'error');if(r.ok)loadReleases()}
async function deleteRelease(id){if(!confirm('Cancellare definitivamente questo snapshot storico?'))return;const r=await fetch('/api/v1/admin/releases/'+encodeURIComponent(id),{method:'DELETE',headers:{Authorization:'Bearer '+adminToken()}});const d=await r.json();releaseMessage.textContent=r.ok?'Snapshot cancellato.':(d.detail||'Cancellazione fallita');releaseMessage.className='progress-message '+(r.ok?'success':'error');if(r.ok)loadReleases()}
async function loadUsers(){const query=new URLSearchParams({search:document.getElementById('userSearch').value.trim(),status:document.getElementById('userStatus').value});const r=await fetch('/api/v1/admin/users?'+query.toString(),{headers:{Authorization:'Bearer '+adminToken()}});const d=await r.json();if(!r.ok){userMessage.textContent=d.detail||'Impossibile caricare gli utenti.';return}document.getElementById('userTotal').textContent=d.stats?.total??d.count;document.getElementById('userActive').textContent=Math.max(0,(d.stats?.total??0)-(d.stats?.admins??0)-(d.stats?.suspended??0));document.getElementById('userSuspended').textContent=d.stats?.suspended??0;document.getElementById('users').innerHTML=d.users.map(user=>`<article class="release-card"><header><strong>${esc(user.email)}</strong><span class="user-state ${user.disabled?'is-suspended':user.is_admin?'is-admin':'is-active'}">${user.is_admin?'Amministratore':user.disabled?'Sospeso':'Attivo'}</span></header><p class="muted">Account #${user.id} · creato ${esc(user.created_at)} · ${user.active_sessions||0} sessioni attive · ${user.ticket_count||0} segnalazioni</p>${user.is_admin?'<span class="muted">Account amministrativo protetto</span>':`<div class="user-actions"><button data-admin-action="revoke-sessions" data-id="${user.id}">Revoca sessioni</button><button data-admin-action="delete-user" data-id="${user.id}" class="danger">Elimina dati</button></div>`}</article>`).join('')||'<div class="empty-state">Nessun account corrisponde ai filtri.</div>'}
async function deleteUser(id){if(!confirm('Eliminare definitivamente account e segnalazioni dell’utente?'))return;const r=await fetch('/api/v1/admin/users/'+id,{method:'DELETE',headers:{Authorization:'Bearer '+adminToken()}});const d=await r.json();userMessage.textContent=r.ok?'Account eliminato.':(d.detail||'Eliminazione fallita');userMessage.className='progress-message '+(r.ok?'success':'error');if(r.ok)loadUsers()}
async function revokeSessions(id){if(!confirm('Revocare tutte le sessioni attive di questo utente?'))return;const r=await fetch('/api/v1/admin/users/'+id+'/revoke-sessions',{method:'POST',headers:{Authorization:'Bearer '+adminToken()}});const d=await r.json();userMessage.textContent=r.ok?'Sessioni revocate: '+d.revoked_sessions:(d.detail||'Revoca fallita');userMessage.className='progress-message '+(r.ok?'success':'error');if(r.ok)loadUsers()}
async function loadTickets(){const status=document.getElementById('filter').value,category=document.getElementById('ticketCategoryFilter').value,search=document.getElementById('ticketSearch').value.trim(),query=new URLSearchParams({status,category,search});const r=await fetch('/api/v1/admin/tickets?'+query.toString(),{headers:{Authorization:'Bearer '+adminToken()}});const d=await r.json();if(!r.ok){document.getElementById('message').textContent=d.detail||'Errore';return}document.getElementById('message').textContent=d.count+' segnalazioni';document.getElementById('tickets').innerHTML=d.tickets.map(t=>`<article class="ticket"><b>${esc(t.subject)}</b><span class="muted"> · ${esc(t.category)} · ${esc(t.status)} · ${esc(t.created_at)}</span><p>${esc(t.description)}</p>${t.logs?`<details><summary>Log</summary><pre>${esc(t.logs)}</pre></details>`:''}<textarea id="r-${t.id}" rows="3" cols="70" aria-label="Risposta alla segnalazione">${esc(t.response||'')}</textarea><br><select id="s-${t.id}" aria-label="Stato della segnalazione">${['open','in_progress','resolved','closed'].map(s=>`<option ${s===t.status?'selected':''}>${s}</option>`).join('')}</select><button data-admin-action="save-ticket" data-id="${t.id}">Salva</button></article>`).join('')}
async function save(id){await fetch('/api/v1/admin/tickets/'+id,{method:'PATCH',headers:{'Content-Type':'application/json',Authorization:'Bearer '+adminToken()},body:JSON.stringify({status:document.getElementById('s-'+id).value,response:document.getElementById('r-'+id).value})});loadTickets()}
function esc(v){return String(v??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]))}
</script></body></html>"""
    admin_html = admin_html.replace("</head>", """<style>
:root{color-scheme:dark;--admin-bg:#070b12;--admin-surface:#0e1725;--admin-raised:#121f31;--admin-line:rgba(157,180,211,.18);--admin-text:#f3f6fb;--admin-muted:#94a6bc;--admin-cyan:#72dcff;--admin-violet:#aa9bff;--admin-green:#83e6b0}
*{box-sizing:border-box}body{position:relative;max-width:none;min-height:100vh;margin:0;padding:34px clamp(18px,4vw,58px) 72px;background:radial-gradient(800px 520px at 8% -10%,rgba(72,126,190,.22),transparent 65%),radial-gradient(760px 520px at 95% 12%,rgba(115,85,184,.15),transparent 68%),var(--admin-bg);color:var(--admin-text);font:15px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}body:before{content:"";position:fixed;inset:0;pointer-events:none;opacity:.13;background-image:linear-gradient(rgba(157,180,211,.08) 1px,transparent 1px),linear-gradient(90deg,rgba(157,180,211,.08) 1px,transparent 1px);background-size:52px 52px;mask-image:linear-gradient(to bottom,black,transparent 75%)}h1{position:relative;max-width:1120px;margin:.25rem auto 1.2rem;font-size:clamp(2.5rem,6vw,5.2rem);line-height:.95;letter-spacing:-.075em}h2{letter-spacing:-.04em;line-height:1.12}p{color:var(--admin-muted);max-width:760px}.admin-kicker{position:relative;max-width:1120px;margin:0 auto;color:var(--admin-cyan);font-size:.7rem;font-weight:850;letter-spacing:.18em}.admin-kicker:before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:9px;background:var(--admin-green);box-shadow:0 0 0 5px rgba(131,230,176,.1)}#loginPanel,#adminPanel{position:relative;max-width:1120px;margin:0 auto}#loginPanel{padding:22px;border:1px solid var(--admin-line);border-radius:18px;background:rgba(14,23,37,.88);box-shadow:0 24px 80px #0005}#loginPanel input{max-width:260px}input,textarea,select{width:100%;background:#080f1b;color:var(--admin-text);border:1px solid var(--admin-line);border-radius:10px;padding:10px 12px;font:inherit;outline:none}input:focus,textarea:focus,select:focus{border-color:var(--admin-cyan);box-shadow:0 0 0 3px rgba(114,220,255,.12)}button{border:1px solid var(--admin-line);border-radius:10px;padding:10px 14px;background:linear-gradient(135deg,#66dbfa,#9b8cff);color:#07101b;font:inherit;font-weight:800;cursor:pointer;transition:transform .18s ease,filter .18s ease}button:hover{transform:translateY(-1px);filter:brightness(1.08)}.progress-panel{position:relative;border:1px solid var(--admin-line);border-radius:18px;padding:clamp(20px,3vw,30px);margin:18px 0;background:linear-gradient(145deg,rgba(18,31,49,.94),rgba(10,17,28,.9));box-shadow:0 20px 60px #0003}.progress-panel>h2{margin-top:0}.progress-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.progress-panel label{margin:0}.progress-message{display:inline-block;margin:10px 0 0 8px}.success{color:var(--admin-green)}.error{color:#ffaaa8}.muted{color:var(--admin-muted);font-size:.88rem}.ticket,.release-card{border:1px solid var(--admin-line);border-radius:14px;padding:18px;margin:14px 0;background:rgba(7,13,22,.5)}.release-card.active{border-color:rgba(114,220,255,.62);box-shadow:0 0 0 1px rgba(114,220,255,.1) inset}.release-card header{display:flex;justify-content:space-between;gap:14px;align-items:center}.release-card .release-actions{margin-top:12px}.danger{background:#822f3c;color:#fff;border-color:#aa4a59}pre{white-space:pre-wrap;overflow:auto;max-height:340px;background:#050a12;border:1px solid var(--admin-line);padding:13px;border-radius:10px}.audit-entry{padding:10px 0;border-bottom:1px solid var(--admin-line)}#message{margin:14px 0;color:var(--admin-muted)}#adminPanel>button:first-child{margin-bottom:12px}@media(max-width:700px){.progress-grid{grid-template-columns:1fr}.release-card header{display:block}#loginPanel input{max-width:none;margin-bottom:8px}}
</style></head>""",1)
    admin_html = admin_html.replace("</head>", """<style>
.section-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:18px}.section-heading h2{margin:.1rem 0 .25rem}.section-badge{border:1px solid var(--admin-line);border-radius:999px;padding:5px 10px;color:var(--admin-cyan);font-size:.68rem;font-weight:800;letter-spacing:.12em}.user-summary{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}.user-summary span{display:flex;align-items:baseline;gap:7px;min-width:112px;padding:11px 13px;border:1px solid var(--admin-line);border-radius:12px;background:rgba(7,13,22,.45)}.user-summary strong{font-size:1.35rem}.user-summary small{color:var(--admin-muted);font-size:.72rem}.user-toolbar,.ticket-toolbar{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap;margin:14px 0 18px}.compact-field{display:flex!important;flex:1 1 180px;gap:5px!important;margin:0!important}.compact-field input,.compact-field select{margin:0!important}.user-toolbar>button{margin:0}.user-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.user-state{display:inline-flex;align-items:center;gap:6px;font-size:.74rem;font-weight:800}.user-state:before{content:"";width:7px;height:7px;border-radius:50%;background:var(--admin-green);box-shadow:0 0 0 4px rgba(131,230,176,.1)}.user-state.is-suspended{color:#ffcf7a}.user-state.is-suspended:before{background:#ffcf7a;box-shadow:0 0 0 4px rgba(255,207,122,.1)}.user-state.is-admin{color:var(--admin-violet)}.user-state.is-admin:before{background:var(--admin-violet);box-shadow:0 0 0 4px rgba(170,155,255,.1)}.empty-state{padding:18px;border:1px dashed var(--admin-line);border-radius:12px;color:var(--admin-muted)}.ticket-toolbar{margin:0}.ticket-toolbar .compact-field{flex:0 1 160px}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}@media(max-width:700px){.section-heading{display:block}.section-badge{display:inline-block;margin-top:10px}.user-toolbar,.ticket-toolbar{align-items:stretch}.user-toolbar>button{width:100%;margin:0}.ticket-toolbar{margin-top:14px}.ticket-toolbar .compact-field{flex:1 1 100%}}
</style></head>""",1)
    admin_html = admin_html.replace("</head>", """<style>
.admin-message-spaced{margin-top:.8rem}.admin-logout{margin-bottom:1rem}.compliance-item{margin:.45rem 0}.compliance-ok{color:#78e0a3}.compliance-warn,.compliance-title-warn{color:#ffcf7a}.compliance-ready{color:#78e0a3}.compliance-missing{margin-top:.8rem}
</style></head>""",1)
    legal_panel = """<section class="progress-panel"><h2>Dati legali del titolare</h2><p class="muted">Questi dati vengono mostrati nella Privacy pubblica. Completa ogni campo prima di rendere definitiva l’informativa del progetto non commerciale.</p><div class="progress-grid"><label>Nome completo / ragione sociale<input id="legalName" autocomplete="organization"></label><label>Email privacy<input id="legalEmail" type="email" autocomplete="email"></label><label>Indirizzo legale<input id="legalAddress" autocomplete="street-address"></label><label>Città e CAP<input id="legalCity" autocomplete="address-level2"></label><label>Partita IVA / codice fiscale<input id="legalVat"></label><label>Autorità di controllo<input id="legalAuthority"></label><label>Basi giuridiche account<input id="legalBasisAccount" maxlength="500"></label><label>Basi giuridiche segnalazioni<input id="legalBasisSupport" maxlength="500"></label><label>Basi giuridiche sicurezza<input id="legalBasisSecurity" maxlength="500"></label><label>Trasferimenti e destinatari<input id="legalTransferInfo" maxlength="1000"></label></div><button id="saveLegalSettingsButton">Salva dati legali</button><button id="confirmLegalReviewButton" class="primary">Conferma revisione del titolare</button><span id="legalMessage" class="progress-message"></span></section><section class="progress-panel"><h2>Checklist di pubblicazione</h2><p class="muted">Controllo tecnico e legale preliminare. Il risultato non sostituisce la revisione del titolare.</p><button id="loadComplianceButton">Aggiorna checklist</button><div id="complianceStatus" class="muted admin-message-spaced">Accedi per eseguire il controllo.</div></section><section class="progress-panel"><h2>Registro sicurezza</h2><p class="muted">Ultime azioni amministrative, senza password, token, IP o contenuti dei ticket.</p><button id="loadAuditButton">Aggiorna registro</button><div id="auditLog" class="muted admin-message-spaced">Accedi per caricare il registro.</div></section>"""
    legal_guidance = """<section class="progress-panel"><h2>Guida alla compilazione</h2><p class="muted">Gli esempi sotto sono orientativi: il titolare deve verificare la base giuridica applicabile alle attività reali prima di confermare la revisione.</p><ul><li><strong>Account:</strong> valuta l’art. 6(1)(b) solo se il trattamento è necessario per fornire la funzione account.</li><li><strong>Segnalazioni:</strong> valuta l’art. 6(1)(f) solo dopo aver documentato il bilanciamento tra assistenza, sicurezza e diritti degli interessati.</li><li><strong>Sicurezza:</strong> indica finalità, dati minimi e periodo di conservazione; non usare il “legittimo interesse” come formula generica.</li><li><strong>Destinatari e trasferimenti:</strong> elenca hosting, reverse proxy, Buy Me a Coffee e ogni altro fornitore effettivamente utilizzato, inclusa l’eventuale localizzazione dei dati.</li></ul><p class="muted"><a href="https://www.edpb.europa.eu/sme/be-compliant/process-personal-data-lawfully_en" target="_blank" rel="noopener">Guida EDPB sulle basi giuridiche</a> · <a href="https://www.garanteprivacy.it/documents/10160/0/VADEMECUM%2B-%2BSocial%2BPrivacy%2B-%2BCome%2Btutelarsi%2Bnell%27epoca%2Bdei%2Bsocial%2Bmedia-%2B2025.pdf/6fa4e17b-835e-80d4-d2c6-533adb2bd6ea?download=true&amp;version=5.0" target="_blank" rel="noopener">Guida del Garante sulla base giuridica</a></p></section>"""
    legal_panel = legal_panel.replace('<section class="progress-panel"><h2>Checklist di pubblicazione', legal_guidance + '<section class="progress-panel"><h2>Checklist di pubblicazione', 1)
    legal_panel = legal_panel.replace('<label>Email privacy<input id="legalEmail"', '<label>Qualifica / forma giuridica<input id="legalType" autocomplete="organization-title"></label><label>Email privacy<input id="legalEmail"')
    legal_panel = legal_panel.replace('<label>Partita IVA / codice fiscale<input id="legalVat"', '<label class="consent-check"><input id="legalPublishAddress" type="checkbox"> Pubblica l’indirizzo completo nella Privacy</label><label>Partita IVA / codice fiscale<input id="legalVat"')
    admin_html = admin_html.replace("${user.is_admin?'Amministratore':'Utente'} · #${user.id}", "${user.is_admin?'Amministratore':(user.disabled?'Sospeso':'Utente')} · #${user.id}")
    admin_html = admin_html.replace('<button data-admin-action="revoke-sessions" data-id="${user.id}">Revoca sessioni</button>', '<button data-admin-action="toggle-user" data-id="${user.id}" data-disabled="${user.disabled?\'1\':\'0\'}">${user.disabled?\'Riattiva\':\'Sospendi\'}</button><button data-admin-action="revoke-sessions" data-id="${user.id}">Revoca sessioni</button>')
    admin_html = admin_html.replace("async function deleteUser(id){", "async function toggleUser(id,disabled){if(!confirm(disabled?'Riattivare questo account?':'Sospendere questo account e revocare le sue sessioni?'))return;const r=await fetch('/api/v1/admin/users/'+id+'/status',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+adminToken()},body:JSON.stringify({disabled})});const d=await r.json();userMessage.textContent=r.ok?(disabled?'Account sospeso.':'Account riattivato.'):(d.detail||'Operazione fallita');userMessage.className='progress-message '+(r.ok?'success':'error');if(r.ok)loadUsers()}\nasync function deleteUser(id){")
    admin_html = admin_html.replace("case 'delete-user':return deleteUser(Number(id));case 'save-ticket':", "case 'delete-user':return deleteUser(Number(id));case 'toggle-user':return toggleUser(Number(id),button.dataset.disabled==='1');case 'save-ticket':")
    admin_html = admin_html.replace("legalName=document.getElementById('legalName'),legalEmail=", "legalName=document.getElementById('legalName'),legalType=document.getElementById('legalType'),legalPublishAddress=document.getElementById('legalPublishAddress'),legalEmail=")
    legal_script = """async function loadLegalSettings(){const r=await fetch('/api/v1/admin/legal-settings',{headers:{Authorization:'Bearer '+adminToken()}});const d=await r.json();if(!r.ok){legalMessage.textContent=d.detail||'Impossibile caricare i dati legali.';return}legalName.value=d.legal_name||'';legalEmail.value=d.contact_email||'';legalAddress.value=d.address||'';legalCity.value=d.city||'';legalVat.value=d.vat_or_tax_id||'';legalAuthority.value=d.supervisory_authority||'';legalBasisAccount.value=d.legal_basis_account||'';legalBasisSupport.value=d.legal_basis_support||'';legalBasisSecurity.value=d.legal_basis_security||'';legalTransferInfo.value=d.transfer_info||'';legalMessage.textContent=d.complete?(d.legal_reviewed_at?'Dati completi e revisione confermata.':'Dati completi, in attesa di conferma del titolare.'):'Dati incompleti.';legalMessage.className='progress-message '+(d.complete?'success':'error')}
async function saveLegalSettings(){const payload={legal_name:legalName.value,address:legalAddress.value,city:legalCity.value,contact_email:legalEmail.value,vat_or_tax_id:legalVat.value,supervisory_authority:legalAuthority.value,legal_basis_account:legalBasisAccount.value,legal_basis_support:legalBasisSupport.value,legal_basis_security:legalBasisSecurity.value,transfer_info:legalTransferInfo.value};const r=await fetch('/api/v1/admin/legal-settings',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+adminToken()},body:JSON.stringify(payload)});const d=await r.json();legalMessage.textContent=r.ok?(d.complete?'Dati legali salvati e completi.':'Salvato, ma mancano dati obbligatori.'):d.detail||'Salvataggio fallito';legalMessage.className='progress-message '+(r.ok&&d.complete?'success':'error');if(r.ok)loadCompliance()}
const _interpresonaLoginAdmin=loginAdmin;loginAdmin=async function(){await _interpresonaLoginAdmin();if(!document.getElementById('adminPanel').hidden){loadLegalSettings();loadCompliance();loadAudit()}}
async function logoutAdmin(){await fetch('/api/v1/auth/logout',{method:'POST'});location.reload()}
const adminLogout=document.createElement('button');adminLogout.type='button';adminLogout.className='admin-logout';adminLogout.textContent='Esci dall’area admin';adminLogout.addEventListener('click',logoutAdmin);document.getElementById('adminPanel').prepend(adminLogout)
async function loadCompliance(){const r=await fetch('/api/v1/admin/compliance',{headers:{Authorization:'Bearer '+adminToken()}});const d=await r.json();if(!r.ok){complianceStatus.textContent=d.detail||'Impossibile eseguire il controllo.';return}const items=Object.values(d.checks).map(item=>`<div class="compliance-item ${item.ok?'compliance-ok':'compliance-warn'}">${item.ok?'✓':'!'} ${esc(item.label)}${item.manual?' <span class="muted">· revisione manuale</span>':''}</div>`).join('');complianceStatus.innerHTML=`<strong class="compliance-title ${d.ready?'compliance-ready':'compliance-title-warn'}">${d.ready?'Pronto per la revisione finale':'Non ancora pronto per la pubblicazione finale'}</strong>${items}`}

async function loadAudit(){const r=await fetch('/api/v1/admin/audit?limit=50',{headers:{Authorization:'Bearer '+adminToken()}});const d=await r.json();if(!r.ok){auditLog.textContent=d.detail||'Impossibile caricare il registro.';return}auditLog.innerHTML=d.events.length?d.events.map(e=>`<div class="audit-entry"><strong>${esc(e.action)}</strong> · ${esc(e.target)}<br><span class="muted">${esc(e.created_at)} · ${esc(e.actor_type)} · ${esc(e.details||'')}</span></div>`).join(''):'Nessuna azione registrata.'}
function bindAdminActions(){document.getElementById('adminLoginButton').addEventListener('click',loginAdmin);document.getElementById('changePasswordButton').addEventListener('click',changePassword);document.getElementById('saveProgressButton').addEventListener('click',saveProgress);document.getElementById('loadUsersButton').addEventListener('click',loadUsers);document.getElementById('userSearch').addEventListener('input',function(){clearTimeout(window._userSearchTimer);window._userSearchTimer=setTimeout(loadUsers,250)});document.getElementById('userStatus').addEventListener('change',loadUsers);document.getElementById('loadTicketsButton').addEventListener('click',loadTickets);document.getElementById('ticketCategoryFilter').addEventListener('change',loadTickets);document.getElementById('filter').addEventListener('change',loadTickets);document.getElementById('ticketSearch').addEventListener('input',function(){clearTimeout(window._ticketSearchTimer);window._ticketSearchTimer=setTimeout(loadTickets,250)});document.getElementById('saveLegalSettingsButton').addEventListener('click',saveLegalSettings);document.getElementById('loadComplianceButton').addEventListener('click',loadCompliance);document.getElementById('loadAuditButton').addEventListener('click',loadAudit);document.getElementById('adminPanel').addEventListener('click',function(event){const button=event.target.closest('[data-admin-action]');if(!button)return;const id=button.dataset.id;switch(button.dataset.adminAction){case 'save-release':return saveRelease(id);case 'delete-release':return deleteRelease(id);case 'revoke-sessions':return revokeSessions(Number(id));case 'delete-user':return deleteUser(Number(id));case 'toggle-user':return toggleUser(Number(id),button.dataset.disabled==='1');case 'save-ticket':return save(id)}})}bindAdminActions();restoreAdminSession()
"""
    legal_script = legal_script.replace("const _interpresonaLoginAdmin=loginAdmin;", "async function confirmLegalReview(){if(!confirm('Confermare la revisione manuale dell’informativa?'))return;const r=await fetch('/api/v1/admin/compliance/confirm',{method:'POST',headers:{Authorization:'Bearer '+adminToken()}});const d=await r.json();legalMessage.textContent=r.ok?'Revisione registrata.':(d.detail||'Impossibile confermare la revisione.');legalMessage.className='progress-message '+(r.ok?'success':'error');if(r.ok)loadCompliance()}\nconst _interpresonaLoginAdmin=loginAdmin;")
    legal_script = legal_script.replace("document.getElementById('loadAuditButton').addEventListener('click',loadAudit);", "document.getElementById('loadAuditButton').addEventListener('click',loadAudit);document.getElementById('confirmLegalReviewButton').addEventListener('click',confirmLegalReview);")
    legal_script = legal_script.replace("legalName=document.getElementById('legalName'),legalEmail=", "legalName=document.getElementById('legalName'),legalType=document.getElementById('legalType'),legalEmail=")
    legal_script = legal_script.replace("legalType=document.getElementById('legalType'),legalEmail=", "legalType=document.getElementById('legalType'),legalPublishAddress=document.getElementById('legalPublishAddress'),legalEmail=")
    legal_script = legal_script.replace("legalName.value=d.legal_name||'';legalEmail.value=", "legalName.value=d.legal_name||'';legalType.value=d.legal_type||'';legalEmail.value=")
    legal_script = legal_script.replace("legalCity.value=d.city||'';legalVat.value=", "legalCity.value=d.city||'';legalPublishAddress.checked=!!d.publish_address;legalVat.value=")
    legal_script = legal_script.replace("{legal_name:legalName.value,address:", "{legal_name:legalName.value,legal_type:legalType.value,address:")
    legal_script = legal_script.replace("city:legalCity.value,contact_email:", "city:legalCity.value,publish_address:legalPublishAddress.checked,contact_email:")
    legal_script = legal_script.replace("\n\nasync function loadAudit", "\nconst _baseLoadCompliance=loadCompliance;loadCompliance=async function(){await _baseLoadCompliance();const r=await fetch('/api/v1/admin/compliance',{headers:{Authorization:'Bearer '+adminToken()}});const d=await r.json();if(r.ok&&d.missing&&d.missing.length){complianceStatus.insertAdjacentHTML('beforeend','<div class=\\\"muted compliance-missing\\\"><strong>Da completare:</strong><br>'+d.missing.map(esc).join('<br>')+'</div>')}}\n\nasync function loadAudit")
    admin_html = admin_html.replace("</section>\n<script>", legal_panel + "</section>\n<script>", 1)
    admin_html = admin_html.replace("</script></body></html>", legal_script + "</script></body></html>", 1)
    return HTMLResponse(admin_html)

# -------------------------------------------------------------
# WEB PORTAL FRONTEND
# -------------------------------------------------------------

def decorate_public_content(title: str, content: str) -> str:
    """Aggiunge percorsi guidati alle pagine pubbliche senza duplicare il layout base."""
    if title == "Traduzione italiana per FFXIV" and not personal_data_collection_allowed():
        content = content.replace(
            "Puoi inviare una segnalazione anche senza account. Con un account opzionale ritrovi storico e risposte in un unico posto.",
            "L’assistenza online è temporaneamente in revisione privacy. Quando sarà riattivata, potrai seguire le risposte con un account opzionale.",
            1,
        )
        content = content.replace("<h2>Hai bisogno di aiuto?</h2>", "<h2>Assistenza in revisione.</h2>", 1)
        content = content.replace('<a class="button primary" href="/support">Apri l’assistenza</a>', '<a class="button primary" href="/support">Vedi lo stato</a>', 1)
    if title == "Segnalazioni":
        content = content.replace(
            "<option>Traduzione</option>",
            "<option>Privacy / GDPR</option><option>Traduzione</option>",
            1,
        )
        content = content.replace(
            '<div id="authMessage" class="muted"></div>',
            '<div id="authMessage" class="muted"></div><div class="panel account-security" id="accountSecurity" hidden><p class="eyebrow">SICUREZZA ACCOUNT</p><div class="two"><label>Password attuale<input id="currentPassword" type="password" minlength="12" autocomplete="current-password"></label><label>Nuova password<input id="newAccountPassword" type="password" minlength="12" autocomplete="new-password"></label></div><button id="changeAccountPasswordButton" type="button">Aggiorna password</button><div id="passwordMessage" class="muted"></div></div>',
            1,
        )
        content = content.replace(
            '<div class="actions"><button id="exportDataButton">Scarica i miei dati</button><button id="deleteAccountButton">Elimina account</button><button id="logoutButton">Esci</button></div>',
            '<div id="accountActions" class="actions" hidden><button id="exportDataButton">Scarica i miei dati</button><button id="deleteAccountButton">Elimina account</button><button id="logoutButton">Esci</button></div>',
            1,
        )
        content = content.replace(
            "document.getElementById('sendTicketButton').addEventListener('click',sendTicket);loadMine();",
            "document.getElementById('sendTicketButton').addEventListener('click',sendTicket);",
            1,
        )
        content = content.replace("if(!token())return msg('mine','Accedi per visualizzare lo storico.');", "")
        content = content.replace("if(!token())return msg('authMessage','Accedi prima di scaricare i dati.');", "")
        content = content.replace("if(!token())return msg('authMessage','Accedi prima di eliminare l’account.');", "")
        content = content.replace("if(token())await fetch(api+'/auth/logout'", "await fetch(api+'/auth/logout'")
        password_script = """\nasync function changeAccountPassword(){const current=document.getElementById('currentPassword'),next=document.getElementById('newAccountPassword');const headers={'Content-Type':'application/json'};const r=await fetch(api+'/auth/change-password',{method:'POST',headers,body:JSON.stringify({current_password:current.value,new_password:next.value})});const d=await r.json();if(!r.ok)return msg('passwordMessage',d.detail||'Accedi prima di cambiare la password.');current.value='';next.value='';msg('passwordMessage','Password aggiornata. Le sessioni precedenti sono state revocate.',true)}\nconst changeAccountPasswordButton=document.getElementById('changeAccountPasswordButton');if(changeAccountPasswordButton)changeAccountPasswordButton.addEventListener('click',changeAccountPassword);const accountActions=document.getElementById('accountActions'),accountSecurity=document.getElementById('accountSecurity');function setAccountState(active){if(accountActions)accountActions.hidden=!active;if(accountSecurity)accountSecurity.hidden=!active}const originalLoadMine=loadMine;loadMine=async function(){const session=await fetch(api+'/auth/me');if(!session.ok){setAccountState(false);return msg('mine','Accedi o registrati per continuare.')}setAccountState(true);await originalLoadMine()};setAccountState(false);loadMine();const requestedCategory=new URLSearchParams(location.search).get('category');if(requestedCategory==='privacy'&&ticketCategory)ticketCategory.value='Privacy / GDPR'\n"""
        content = content.replace("</script>", password_script + "</script>", 1)
    if title == "Privacy":
        content += '<section class="panel privacy-action"><p class="eyebrow">ESERCITA I TUOI DIRITTI</p><h2>Hai una richiesta sulla privacy?</h2><p>Per accesso, rettifica, cancellazione o chiarimenti puoi usare il modulo assistenza e scegliere la categoria Privacy / GDPR.</p><div class="actions"><a class="button primary" href="/support?category=privacy">Apri una richiesta privacy</a></div></section>'
    return content


PUBLIC_POLISH_CSS = """<style>
.page-content{animation:interpresona-enter .42s ease both}
.page-content h1,.page-content h2{font-family:Georgia,'Times New Roman',serif;font-weight:600}
.page-content h1{font-size:clamp(2.25rem,5.8vw,4.85rem);letter-spacing:-.055em}
.page-content h2{letter-spacing:-.025em}
.page-content a:focus-visible,.page-content button:focus-visible,.page-content input:focus-visible,.page-content textarea:focus-visible,.page-content select:focus-visible{outline:2px solid var(--cyan);outline-offset:3px}
@keyframes interpresona-enter{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}.page-content{animation:none}.card:hover,.button:hover,button:hover{transform:none}}
.hero{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(280px,.65fr);gap:clamp(28px,6vw,86px);align-items:center;margin:clamp(34px,7vw,78px) 0 30px;padding:clamp(28px,5vw,64px);border:1px solid rgba(157,180,211,.2);border-radius:28px;background:linear-gradient(122deg,rgba(20,42,62,.94),rgba(12,20,32,.96) 60%,rgba(39,29,71,.88));box-shadow:0 30px 90px rgba(0,0,0,.3);overflow:hidden;position:relative}.hero:after{content:"";position:absolute;width:440px;height:440px;right:-180px;top:-210px;border-radius:50%;border:1px solid rgba(114,220,255,.18);box-shadow:0 0 0 28px rgba(114,220,255,.025),0 0 0 56px rgba(114,220,255,.025);pointer-events:none}.hero-copy{position:relative;z-index:1}.hero-status{display:flex;align-items:center;gap:10px;margin:0 0 30px;color:var(--muted);font-size:.78rem;font-weight:700;letter-spacing:.02em}.hero-status-separator{color:var(--line-strong)}.hero h1{font-size:clamp(2.9rem,6.7vw,6.3rem);max-width:780px;margin:.4rem 0 1.4rem}.hero h1 em,.section-intro h2 em,.contact-band h2 em{font-style:normal;color:var(--cyan)}.hero .lead{max-width:620px}.hero-note{font-size:.78rem;color:rgba(243,246,251,.6);margin-top:18px}.hero-release{position:relative;z-index:1;min-height:270px;display:grid;place-items:center;border:1px solid rgba(114,220,255,.26);border-radius:24px;background:radial-gradient(circle at 50% 40%,rgba(114,220,255,.16),transparent 52%),rgba(7,13,22,.5);overflow:hidden}.hero-orbit{position:absolute;inset:0;display:grid;place-items:center;opacity:.9}.hero-orbit svg{width:min(86%,290px);height:auto}.hero-orbit circle{fill:none;stroke:rgba(114,220,255,.38);stroke-width:1}.hero-orbit circle:first-child{stroke-dasharray:2 7}.hero-orbit path{fill:none;stroke:rgba(157,180,211,.18);stroke-width:1}.hero-orbit path:last-child{fill:rgba(114,220,255,.12);stroke:#72dcff;stroke-width:1.5}.hero-release-copy{position:relative;display:grid;justify-items:center;gap:8px;text-align:center}.hero-release-copy strong{font-size:clamp(3.3rem,6vw,5.2rem);letter-spacing:-.09em;line-height:.9}.hero-release-copy>span:last-child{color:var(--muted);font-size:.85rem;max-width:180px}.release-strip{display:grid;grid-template-columns:repeat(3,1fr) auto;gap:1px;margin:0 0 clamp(60px,8vw,100px);border:1px solid var(--line);border-radius:16px;overflow:hidden;background:var(--line)}.release-strip>div,.strip-link{min-height:92px;display:flex;flex-direction:column;justify-content:center;padding:18px 22px;background:rgba(13,20,32,.92)}.release-strip strong{margin-top:7px;font-size:1rem}.strip-link{color:var(--cyan);text-decoration:none;font-size:.85rem;font-weight:800;white-space:nowrap}.strip-link span{margin-left:7px;font-size:1.1rem}.workflow{margin:0 0 clamp(60px,9vw,108px)}.section-intro{max-width:650px}.section-intro h2{font-size:clamp(2.25rem,5vw,4.4rem);margin:.35rem 0 1rem}.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:0;margin-top:38px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.step{display:flex;gap:17px;padding:27px 24px 27px 0;border-right:1px solid var(--line)}.step+.step{padding-left:24px}.step:last-child{border-right:0}.step-number{color:var(--cyan);font-size:.72rem;font-weight:850;letter-spacing:.12em;padding-top:5px}.step h3{font-size:1.05rem;margin:0 0 6px}.step p{font-size:.9rem;margin:0}.workflow-foot{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-top:18px;color:var(--muted);font-size:.78rem}.workflow-foot span+span:before{content:"·";margin-right:16px;color:var(--line-strong)}.workflow-foot a{margin-left:auto;font-weight:700;text-decoration:none}.contact-band{display:flex;justify-content:space-between;align-items:center;gap:26px;margin:0 0 clamp(60px,9vw,108px);padding:clamp(26px,4vw,44px);border-radius:22px;background:linear-gradient(100deg,rgba(22,39,59,.95),rgba(24,22,49,.88));border:1px solid var(--line)}.contact-band h2{font-size:clamp(1.8rem,3.8vw,3rem);margin:.3rem 0 .7rem}.contact-band p{max-width:590px}.contact-band .actions{margin:0}.progress-section{display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr);gap:clamp(28px,7vw,90px);align-items:center;padding-top:8px}.progress-list{display:grid;gap:25px}.progress-row{padding-bottom:21px;border-bottom:1px solid var(--line)}.progress-label{display:flex;justify-content:space-between;gap:16px;margin-bottom:11px;font-size:.9rem}.progress-label strong{color:var(--cyan)}.progress-row:last-child .progress-label strong{color:var(--green)}.progress-track{height:9px;border-radius:99px;background:#070d16;overflow:hidden;border:1px solid rgba(157,180,211,.12)}.progress-fill{display:block;height:100%;border-radius:inherit}.progress-fill-ai{background:linear-gradient(90deg,#66dbfa,#9b8cff)}.progress-fill-human{background:linear-gradient(90deg,#83e6b0,#66dbfa)}.legal-note{margin-top:60px!important;font-size:.76rem}.page-content>.panel:first-child{margin-top:34px}
@media(max-width:820px){.hero{grid-template-columns:1fr}.hero-release{min-height:210px;max-width:360px}.release-strip{grid-template-columns:repeat(2,1fr)}.strip-link{grid-column:1/-1;min-height:60px}.steps{grid-template-columns:1fr}.step,.step+.step{padding:21px 0;border-right:0;border-bottom:1px solid var(--line)}.step:last-child{border-bottom:0}.workflow-foot a{margin-left:0}.contact-band,.progress-section{display:block}.progress-list{margin-top:34px}}
@media(max-width:520px){.hero{border-radius:20px;padding:24px 20px}.hero h1{font-size:clamp(2.6rem,13vw,4.2rem)}.release-strip{grid-template-columns:1fr}.release-strip>div,.strip-link{min-height:70px}.contact-band{padding:24px 20px}.contact-band .actions{margin-top:22px}.workflow-foot{display:block}.workflow-foot span{display:block;margin-bottom:6px}.workflow-foot span+span:before{display:none}}
.progress-meter{display:block;width:100%;height:10px;border:1px solid rgba(157,180,211,.12);border-radius:99px;background:#070d16;overflow:hidden}.progress-meter::-webkit-progress-bar{background:#070d16;border-radius:99px}.progress-meter::-webkit-progress-value{border-radius:99px}.progress-meter::-moz-progress-bar{border-radius:99px}.progress-meter-ai::-webkit-progress-value{background:linear-gradient(90deg,#66dbfa,#9b8cff)}.progress-meter-ai::-moz-progress-bar{background:linear-gradient(90deg,#66dbfa,#9b8cff)}.progress-meter-human::-webkit-progress-value{background:linear-gradient(90deg,#83e6b0,#66dcff)}.progress-meter-human::-moz-progress-bar{background:linear-gradient(90deg,#83e6b0,#66dcff)}.ticket-history{margin-top:12px}
.table-wrap{overflow-x:auto;margin-top:18px}.cookie-table{width:100%;border-collapse:collapse;min-width:520px;color:var(--muted);font-size:.88rem}.cookie-table th,.cookie-table td{padding:13px 14px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}.cookie-table th{color:var(--text);font-size:.75rem;letter-spacing:.08em;text-transform:uppercase}.cookie-table code{color:var(--cyan);font-size:.8rem}
/* Passaggio editoriale: meno decorazione, più prodotto. */
*[hidden]{display:none!important}body::before{display:none}.consent-banner{position:relative;left:auto;right:auto;bottom:auto;margin:18px 0 0;z-index:2}.page-content h1,.page-content h2{font-family:inherit;font-weight:760;letter-spacing:-.045em}.page-content h1{font-size:clamp(2.35rem,5.2vw,5.1rem)}.page-content h2{font-size:clamp(1.65rem,3.2vw,3rem)}.eyebrow,.number{letter-spacing:.1em}.hero{border-radius:18px;background:linear-gradient(115deg,#142332 0%,#101924 58%,#172337 100%);box-shadow:0 20px 60px rgba(0,0,0,.24)}.hero:after{opacity:.42}.hero h1{font-size:clamp(2.7rem,5.8vw,5.6rem);letter-spacing:-.07em}.hero h1 em,.section-intro h2 em,.contact-band h2 em{color:var(--yellow)}.hero-release{min-height:236px;border-radius:16px;background:rgba(5,12,21,.34);box-shadow:inset 0 0 0 1px rgba(255,255,255,.025)}.hero-orbit{opacity:.52}.hero-release-copy strong{font-family:inherit;font-weight:780}.release-strip{border-radius:12px;box-shadow:0 14px 40px rgba(0,0,0,.13)}.release-strip>div,.strip-link{min-height:82px}.steps{margin-top:30px}.step{padding-top:22px;padding-bottom:22px}.contact-band{border-radius:16px}.legal-note{border-top:1px solid var(--line);padding-top:18px}
.privacy-rights .actions{margin-bottom:0}.button.danger,button.danger{background:linear-gradient(135deg,#8f4351,#5e2634);border-color:#b35a69;color:#fff}
</style>"""


def public_shell(title: str, content: str) -> HTMLResponse:
    safe_title = escape(title)
    content = decorate_public_content(title, content)
    return HTMLResponse(f"""<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{safe_title} · Interpresona</title><style>
:root{{color-scheme:dark;--bg:#070b12;--surface:#0d1420;--surface-raised:#111b2b;--line:rgba(157,180,211,.17);--line-strong:rgba(157,180,211,.30);--text:#f3f6fb;--muted:#9aa9bc;--cyan:#72dcff;--violet:#aa9bff;--green:#83e6b0;--yellow:#ffda70;--shadow:0 24px 80px rgba(0,0,0,.28)}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;min-width:320px;background:radial-gradient(900px 520px at 12% -8%,rgba(72,126,190,.23),transparent 65%),radial-gradient(720px 460px at 95% 18%,rgba(115,85,184,.16),transparent 68%),var(--bg);color:var(--text);font:16px/1.6 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}body::before{{content:"";position:fixed;inset:0;pointer-events:none;opacity:.16;background-image:linear-gradient(rgba(157,180,211,.08) 1px,transparent 1px),linear-gradient(90deg,rgba(157,180,211,.08) 1px,transparent 1px);background-size:52px 52px;mask-image:linear-gradient(to bottom,black,transparent 75%)}}a{{color:var(--cyan);text-underline-offset:3px}}main{{position:relative;max-width:1160px;margin:auto;padding:24px clamp(18px,4vw,54px) 70px}}.site-header{{display:flex;justify-content:space-between;align-items:center;gap:24px;padding:6px 0 22px;border-bottom:1px solid var(--line);flex-wrap:wrap}}.brand{{display:inline-flex;align-items:center;gap:10px;color:var(--text);font-weight:850;letter-spacing:.08em;text-decoration:none;font-size:.83rem}}.brand-mark{{display:grid;place-items:center;width:30px;height:30px;border:1px solid rgba(114,220,255,.55);border-radius:10px;color:#07111b;background:linear-gradient(135deg,var(--cyan),var(--violet));box-shadow:0 0 28px rgba(114,220,255,.18);font-size:1rem}}.links{{display:flex;align-items:center;gap:5px;flex-wrap:wrap}}.links a{{color:var(--muted);font-size:.85rem;font-weight:650;text-decoration:none;padding:7px 10px;border-radius:8px;transition:background .2s ease,color .2s ease}}.links a:hover,.links a:focus-visible{{color:var(--text);background:rgba(157,180,211,.09)}}.eyebrow,.number{{color:var(--violet);font-size:.72rem;font-weight:800;letter-spacing:.16em;text-transform:uppercase}}h1{{font-size:clamp(2.45rem,7vw,5.8rem);line-height:.98;letter-spacing:-.075em;margin:.35rem 0 1.25rem;max-width:900px}}h2{{font-size:clamp(1.45rem,3vw,2.2rem);letter-spacing:-.045em;line-height:1.1;margin:0 0 .6rem}}h3{{letter-spacing:-.025em;margin:.2rem 0 .45rem}}p{{color:var(--muted);max-width:760px;margin:.55rem 0}}.lead{{font-size:1.13rem;max-width:650px}}.panel{{background:linear-gradient(145deg,rgba(17,27,43,.91),rgba(10,17,28,.88));border:1px solid var(--line);border-radius:20px;padding:clamp(20px,3vw,32px);margin:22px 0;box-shadow:var(--shadow)}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}}.card{{background:rgba(7,13,22,.55);border:1px solid var(--line);border-radius:15px;padding:20px;min-height:140px;transition:border-color .2s ease,transform .2s ease}}.card:hover{{border-color:var(--line-strong);transform:translateY(-2px)}}.card strong{{display:block;margin:.55rem 0 .25rem}}.card p,.note{{margin:0;color:var(--muted);font-size:.92rem}}.button,button{{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:42px;border-radius:10px;padding:10px 15px;text-decoration:none;font:inherit;font-size:.9rem;font-weight:750;border:1px solid var(--line-strong);color:var(--text);background:rgba(17,27,43,.86);cursor:pointer;transition:transform .2s ease,border-color .2s ease,background .2s ease,filter .2s ease}}.button:hover,button:hover{{border-color:rgba(114,220,255,.58);transform:translateY(-1px)}}.button.primary,.primary{{background:linear-gradient(135deg,#66dbfa,#9b8cff);border-color:transparent;color:#07101b;box-shadow:0 10px 28px rgba(100,177,238,.2)}}.actions{{display:flex;gap:10px;flex-wrap:wrap;margin:26px 0}}label{{display:flex;flex-direction:column;gap:6px;color:var(--muted);font-size:.86rem;margin:12px 0}}input,textarea,select{{width:100%;background:#080f1b;color:var(--text);border:1px solid var(--line-strong);border-radius:10px;padding:11px 12px;font:inherit;outline:none}}input:focus,textarea:focus,select:focus{{border-color:var(--cyan);box-shadow:0 0 0 3px rgba(114,220,255,.12)}}textarea{{min-height:110px;resize:vertical}}.two{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}.consent-check{{display:flex;flex-direction:row;align-items:flex-start;gap:8px;line-height:1.4}}.consent-check input{{width:auto;margin-top:5px}}.muted{{color:var(--muted);font-size:.88rem}}.success{{color:var(--green)}}.error{{color:#ffaaa8}}.donation-widget a{{display:inline-flex;align-items:center;gap:7px;background:var(--yellow);color:#17120a;border:1px solid #1c1708;border-radius:999px;padding:7px 12px;font-size:.75rem;font-weight:850;white-space:nowrap;box-shadow:0 7px 22px rgba(255,218,112,.12)}}footer{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;border-top:1px solid var(--line);padding-top:22px;margin-top:58px;color:var(--muted);font-size:.78rem}}footer a{{color:var(--muted);margin-left:8px}}.consent-banner{{position:fixed;left:clamp(12px,3vw,34px);right:clamp(12px,3vw,34px);bottom:18px;z-index:20;display:flex;justify-content:space-between;gap:20px;align-items:center;padding:17px 20px;background:rgba(13,20,32,.96);backdrop-filter:blur(16px);border:1px solid var(--line-strong);border-radius:16px;box-shadow:0 24px 80px #000b}}.consent-banner[hidden]{{display:none}}.consent-banner p{{margin:4px 0 0;font-size:.84rem}}.consent-banner a{{color:var(--cyan)}}.consent-actions{{display:flex;gap:8px;flex-shrink:0}}.consent-actions button{{font-size:.78rem;white-space:nowrap}}.consent-primary{{background:var(--yellow);color:#17120a;border-color:var(--yellow)}}.status-dot{{display:inline-flex;align-items:center;gap:7px;color:var(--green);font-size:.78rem;font-weight:700}}.status-dot::before{{content:"";width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 0 5px rgba(131,230,176,.1)}}.tag{{display:inline-flex;border:1px solid var(--line-strong);border-radius:999px;padding:4px 9px;color:var(--muted);font-size:.72rem;font-weight:700}}ul{{padding-left:1.2rem;color:var(--muted)}}li+li{{margin-top:.45rem}}
@media(max-width:720px){{.site-header{{align-items:flex-start}}.links{{width:100%}}.links a{{padding-left:0;padding-right:10px}}.grid,.two{{grid-template-columns:1fr}}.consent-banner{{display:block}}.consent-actions{{margin-top:13px;flex-wrap:wrap}}}}
</style>{PUBLIC_POLISH_CSS}</head><body><main><header class="site-header"><a class="brand" href="/"><span class="brand-mark">✦</span><span>INTERPRESONA</span></a><nav class="links" aria-label="Navigazione principale"><a href="/installer">Installer</a><a href="/status">Stato</a><a href="/support">Segnalazioni</a><a href="/about">Progetto</a>{DONATION_WIDGET}</nav></header><div class="page-content">{content}</div><footer><span>Interpresona · traduzione italiana per FFXIV</span><span aria-hidden="true">·</span><span>Progetto indipendente e non commerciale.</span><span>I file vengono gestiti dall’installer.</span><a href="/privacy">Privacy</a><a href="/cookies">Cookie</a><a href="/terms">Termini</a></footer></main>{COOKIE_CONSENT}</body></html>""")


@app.exception_handler(404)
async def not_found_page(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Risorsa non trovata."}, status_code=404)
    response = public_shell("Pagina non trovata", """<p class="eyebrow">ERRORE 404</p><h1>Pagina non trovata.</h1><p>Il collegamento potrebbe essere scaduto o scritto in modo errato. Puoi tornare alla home oppure contattare l’assistenza.</p><div class="actions"><a class="button primary" href="/">Torna alla home</a><a class="button" href="/support">Apri l’assistenza</a></div>""")
    response.status_code = 404
    return response


@app.get("/installer", response_class=HTMLResponse)
def installer_section():
    labels = {
        "linux-x86_64": "Linux 64 bit",
        "windows-x86_64": "Windows 64 bit",
        "macos-x86_64": "macOS Intel",
        "macos-arm64": "macOS Apple Silicon",
    }
    native = available_installer_packages()
    native_actions = "".join(
        f'<a class="button" href="/api/v1/download/installer/{escape(platform_name)}">Scarica {escape(labels.get(platform_name, platform_name))}</a>'
        for platform_name in native
    )
    native_panel = (
        f'<div class="panel"><strong>Pacchetti nativi</strong><p>Questi pacchetti non richiedono Python. Scegli il sistema operativo, avvia l’app e indica soltanto la cartella di FFXIV.</p><div class="actions">{native_actions}</div></div>'
        if native_actions else
        '<div class="panel"><strong>Pacchetti nativi in preparazione</strong><p>Il pacchetto portatile è disponibile subito; i pacchetti nativi per Windows, Linux e macOS vengono pubblicati automaticamente quando il build della piattaforma è pronto.</p></div>'
    )
    return public_shell("Installer", f"""<p class="eyebrow">INSTALLER PUBBLICO</p><h1>Installa la traduzione.</h1><p>L’installer chiede la cartella di FFXIV, controlla la release compatibile, scarica gli EXD verificati e applica la traduzione con backup e ripristino.</p><div class="actions"><a class="button primary" href="/api/v1/download/installer">Scarica il pacchetto portatile</a><a class="button" href="/status">Verifica la release</a></div>{native_panel}<div class="grid"><article class="card"><strong>1. Avvia</strong><p>Apri l’app nativa oppure estrai il pacchetto portatile e avvia il launcher indicato.</p></article><article class="card"><strong>2. Configura</strong><p>Indica la cartella di FFXIV: il programma verifica automaticamente SQPACK e compatibilità.</p></article><article class="card"><strong>3. Applica</strong><p>Conferma l’operazione: crea il backup, mostra il progresso e installa gli EXD.</p></article></div><div class="panel"><strong>Download gestito dall’installer</strong><p>Il sito distribuisce solo l’applicazione. Gli EXD e gli aggiornamenti successivi vengono gestiti direttamente dall’installer; non devi scaricare CSV manualmente.</p></div>""")


@app.get("/status", response_class=HTMLResponse)
def public_status():
    manifest = get_manifest()
    version = escape(str(manifest.get("version", "n/d")))
    patch = escape(str(manifest.get("game_patch", "n/d")))
    updated = escape(str(manifest.get("last_updated", "n/d"))[:19].replace("T", " "))
    total_files = int(manifest.get("total_files", 0))
    return public_shell("Stato", f"""<p class="eyebrow">STATO DELLA DISTRIBUZIONE</p><h1>Release corrente.</h1><div class="grid"><article class="card"><strong>Versione</strong><p>{version}</p></article><article class="card"><strong>Patch</strong><p>{patch}</p></article><article class="card"><strong>Moduli</strong><p>{total_files}</p></article></div><div class="panel"><strong>Ultimo aggiornamento</strong><p>{updated}</p><p class="muted">L’installer utilizza questi dati per verificare la compatibilità e gli aggiornamenti.</p></div>""")


@app.get("/about", response_class=HTMLResponse)
def about_section():
    return public_shell("Progetto", """<p class="eyebrow">IL PROGETTO</p><h1>Interpresona.</h1><p>Un progetto indipendente e non commerciale per rendere Final Fantasy XIV più accessibile ai giocatori italiani, con un flusso controllato, reversibile e aggiornabile.</p><div class="panel"><h2>Come lavoriamo</h2><p>La traduzione viene verificata nell’Admin Studio, pubblicata come release compatibile e distribuita dall’installer. Il portale pubblico non espone i file di lavoro.</p><p>Installer e traduzione sono gratuiti per uso personale. Non vendiamo accessi, abbonamenti o servizi; chi vuole può lasciare una donazione volontaria tramite Buy Me a Coffee, senza ottenere funzioni o aggiornamenti esclusivi.</p></div><div class="actions"><a class="button primary" href="/installer">Scarica l’installer</a><a class="button" href="/support">Apri l’assistenza</a></div>""")


@app.get("/privacy", response_class=HTMLResponse)
def privacy_section():
    legal = legal_settings()
    notice_version = escape(PRIVACY_NOTICE_VERSION)
    legal_name = escape(legal["legal_name"])
    legal_type = escape(legal["legal_type"])
    legal_name = f'{legal_name}<br><span class="muted">{legal_type}</span>'
    address = escape(" · ".join(item for item in ((legal["address"] if legal.get("publish_address") else ""), legal["city"]) if item))
    contact_email = escape(legal["contact_email"])
    vat_id = escape(legal["vat_or_tax_id"])
    tax_line = f"<br>Codice fiscale / partita IVA: {vat_id}" if legal.get("vat_or_tax_id") else ""
    authority = escape(legal["supervisory_authority"])
    legal_ready = legal["complete"] and legal["legal_basis_account"] and legal["legal_basis_support"] and legal["legal_basis_security"] and legal["transfer_info"]
    legal_status = "Informativa pubblicata e revisionata dal titolare" if legal.get("legal_reviewed_at") else "Informativa pubblicata"
    return public_shell("Privacy", f"""<p class="eyebrow">TRASPARENZA</p><h1>Informativa privacy</h1><p>Questa informativa descrive il trattamento dei dati personali del portale Interpresona. Versione informativa: {notice_version}.</p><section class="panel"><h2>Titolare del trattamento</h2><p><strong>{legal_name}</strong><br>{address}{tax_line}<br>Contatto privacy: <a href="mailto:{contact_email}">{contact_email}</a></p><p class="muted">{legal_status}</p></section><section class="panel"><h2>Quali dati trattiamo</h2><ul><li>Account: email, password trasformata in hash, date tecniche di creazione e sessione.</li><li>Segnalazioni: oggetto, descrizione, categoria, eventuali log, email facoltativa, stato e risposta.</li><li>Sicurezza: indirizzo IP tecnico della richiesta, usato per prevenire abusi e attacchi.</li><li>Preferenze privacy: una scelta locale nel browser per ricordare se attivare servizi esterni.</li></ul><p>Salvo quanto indicato sopra, i dati vengono raccolti direttamente dall’interessato o generati tecnicamente durante l’uso del servizio.</p></section><section class="panel"><h2>Finalità e basi giuridiche</h2><p><strong>Account:</strong> {escape(legal["legal_basis_account"])}<br><strong>Segnalazioni e assistenza:</strong> {escape(legal["legal_basis_support"])}<br><strong>Sicurezza del portale:</strong> {escape(legal["legal_basis_security"])}</p><p>Non vengono effettuati profilazione, pubblicità comportamentale o decisioni basate esclusivamente su trattamenti automatizzati.</p></section><section class="panel"><h2>Conservazione, destinatari e trasferimenti</h2><p>Gli indirizzi IP vengono rimossi automaticamente dopo 30 giorni. Le segnalazioni chiuse vengono eliminate dopo 365 giorni; gli account restano fino alla cancellazione richiesta dall’utente. Le sessioni scadute vengono eliminate durante gli accessi successivi.</p><p><strong>Destinatari, fornitori e trasferimenti:</strong> {escape(legal["transfer_info"])}</p><p>Il portale non usa analytics o pubblicità. Il widget Buy Me a Coffee viene caricato solo dopo il consenso ai servizi esterni e comporta una richiesta verso il relativo fornitore.</p></section><section class="panel"><h2>I tuoi diritti</h2><p>Puoi chiedere accesso, copia, rettifica, cancellazione, limitazione od opposizione scrivendo a <a href="mailto:{contact_email}">{contact_email}</a>. Se hai un account puoi usare la sezione Segnalazioni.</p><p>Hai inoltre diritto a proporre reclamo all’autorità di controllo competente. In Italia: <a href="https://www.garanteprivacy.it" target="_blank" rel="noopener">Garante per la protezione dei dati personali</a>.</p><p class="muted">Autorità indicata: {authority}.</p></section>""")


@app.get("/cookies", response_class=HTMLResponse)
def cookies_section():
    return public_shell("Cookie e servizi esterni", """<p class="eyebrow">CONTROLLO PRIVACY</p><h1>Cookie e servizi esterni</h1><p class="lead">Qui trovi una spiegazione breve e concreta di ciò che viene salvato nel browser e di ciò che resta opzionale.</p><section class="panel"><h2>Cookie tecnici</h2><p>Il portale non usa cookie di profilazione e non integra analytics. Il cookie di sessione serve esclusivamente a mantenere l’accesso a supporto e area amministrativa.</p><div class="table-wrap"><table class="cookie-table"><thead><tr><th>Nome</th><th>Funzione</th><th>Durata</th></tr></thead><tbody><tr><td><code>interpresona_session</code></td><td>Sessione autenticata, protetta da HttpOnly, Secure e SameSite=Lax</td><td>30 giorni utente · 8 ore admin</td></tr></tbody></table></div></section><section class="panel"><h2>Preferenza locale</h2><p><code>interpresona_privacy_choice</code> viene salvata nel localStorage del browser per ricordare se hai abilitato servizi esterni. Dura 180 giorni e non è un cookie HTTP; puoi rimuoverla con il pulsante qui sotto.</p><button class="primary" id="resetPrivacyButton">Rivedi le preferenze</button></section><section class="panel"><h2>Buy Me a Coffee</h2><p>Il widget ufficiale non viene caricato al primo accesso. Solo selezionando “Abilita servizi esterni” il browser caricherà lo script del fornitore per mostrare il pulsante di donazione volontaria. Puoi continuare a usare il portale e l’installer scegliendo “Solo necessarie”.</p><p class="muted"><a href="https://www.garanteprivacy.it/temi/cookie" target="_blank" rel="noopener">Linee guida del Garante su cookie e strumenti di tracciamento</a></p></section>""")


@app.get("/terms", response_class=HTMLResponse)
def terms_section():
    return public_shell("Termini", """<p class="eyebrow">UTILIZZO RESPONSABILE</p><h1>Termini del progetto</h1><section class="panel"><h2>Scopo</h2><p>Interpresona è un progetto indipendente e non commerciale di localizzazione. L’installer e i file sono distribuiti gratuitamente per facilitare l’uso personale e possono richiedere aggiornamenti quando il gioco cambia.</p><p>Non è richiesto alcun pagamento per usare il progetto. Eventuali donazioni tramite Buy Me a Coffee sono facoltative, non costituiscono un acquisto e non garantiscono accesso preferenziale, assistenza prioritaria o contenuti esclusivi.</p></section><section class="panel"><h2>Responsabilità</h2><p>Prima di applicare file al gioco crea sempre un backup. L’utente deve verificare la compatibilità con la propria installazione e rispettare i termini applicabili del gioco e della piattaforma.</p></section><section class="panel"><h2>Contatti e segnalazioni</h2><p>Per assistenza usa la pagina Segnalazioni. Per richieste privacy o legali contatta il gestore all’indirizzo indicato nella pagina Privacy.</p></section>""")


@app.get("/support", response_class=HTMLResponse)
def support_section():
    if not personal_data_collection_allowed():
        contact_email = escape(legal_settings()["contact_email"])
        return public_shell("Assistenza", f"""<p class="eyebrow">ASSISTENZA</p><h1>Assistenza online.</h1><p>Invia una segnalazione senza account oppure crea un account gratuito per consultare lo storico e le risposte.</p><section class="panel privacy-gate"><h2>Servizio non disponibile</h2><p>La raccolta dati è momentaneamente sospesa per una verifica tecnica. Puoi consultare l’informativa privacy o contattare il titolare per richieste relative ai dati personali.</p><p>Contatto privacy: <a href="mailto:{contact_email}">{contact_email}</a>.</p></section><section class="panel privacy-rights"><p class="eyebrow">DIRITTI DELL’ACCOUNT</p><h2>Hai già un account?</h2><p>Gli account esistenti possono accedere, scaricare i propri dati o richiederne la cancellazione.</p><div class="two"><label>Email<input id="rightsEmail" type="email" autocomplete="username"></label><label>Password<input id="rightsPassword" type="password" autocomplete="current-password"></label></div><div class="actions"><button id="rightsLoginButton" class="primary" type="button">Accedi</button><button id="rightsLogoutButton" type="button" hidden>Esci</button></div><div id="rightsMessage" class="muted" aria-live="polite"></div><div id="rightsActions" class="actions" hidden><button id="rightsExportButton" type="button">Scarica i miei dati</button><button id="rightsDeleteButton" class="danger" type="button">Elimina account</button></div></section><div class="actions"><a class="button primary" href="/">Torna alla home</a><a class="button" href="/privacy">Leggi la privacy</a></div><script>
const rightsMessage=document.getElementById('rightsMessage'),rightsActions=document.getElementById('rightsActions'),rightsLoginButton=document.getElementById('rightsLoginButton'),rightsLogoutButton=document.getElementById('rightsLogoutButton');
function rightsMsg(text,ok=false){{rightsMessage.textContent=text;rightsMessage.className=ok?'success':'error'}}
function showRightsActions(visible){{rightsActions.hidden=!visible;rightsLogoutButton.hidden=!visible;rightsLoginButton.hidden=visible}}
async function rightsLogin(){{const r=await fetch('/api/v1/auth/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email:document.getElementById('rightsEmail').value,password:document.getElementById('rightsPassword').value}})}});const d=await r.json();if(!r.ok)return rightsMsg(d.detail||'Accesso fallito.');showRightsActions(true);rightsMsg('Accesso effettuato. Ora puoi gestire i tuoi dati.',true);document.getElementById('rightsPassword').value=''}}
async function rightsExport(){{const r=await fetch('/api/v1/auth/export');const d=await r.json();if(!r.ok)return rightsMsg(d.detail||'Impossibile preparare l’export.');const blob=new Blob([JSON.stringify(d,null,2)],{{type:'application/json'}}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='interpresona-dati.json';link.click();URL.revokeObjectURL(url);rightsMsg('Export dei dati preparato.',true)}}
async function rightsDelete(){{const password=prompt('Inserisci la password per confermare l’eliminazione definitiva dell’account.');if(!password)return;const r=await fetch('/api/v1/auth/delete',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{password}})}});const d=await r.json();if(!r.ok)return rightsMsg(d.detail||'Impossibile eliminare l’account.');showRightsActions(false);rightsMsg('Account e dati associati eliminati.',true)}}
async function rightsLogout(){{await fetch('/api/v1/auth/logout',{{method:'POST'}});showRightsActions(false);rightsMsg('Sessione chiusa.',true)}}
rightsLoginButton.addEventListener('click',rightsLogin);document.getElementById('rightsExportButton').addEventListener('click',rightsExport);document.getElementById('rightsDeleteButton').addEventListener('click',rightsDelete);rightsLogoutButton.addEventListener('click',rightsLogout);
</script>""")
    return public_shell("Segnalazioni", """<p class="eyebrow">ASSISTENZA</p><h1>Segnala un problema.</h1><p>Invia una segnalazione senza account oppure crea un account gratuito per consultare lo storico e le risposte. Prima dell’invio leggi l’<a href="/privacy">informativa privacy</a>.</p><div class="two"><section class="panel"><h2>Account facoltativo</h2><label>Email<input id="authEmail" type="email" autocomplete="email"></label><label>Password<input id="authPassword" type="password" minlength="12" autocomplete="new-password"></label><div class="actions"><button id="registerButton" class="primary">Crea account</button><button id="loginButton">Accedi</button></div><div class="actions"><button id="exportDataButton">Scarica i miei dati</button><button id="deleteAccountButton">Elimina account</button><button id="logoutButton">Esci</button></div><div id="authMessage" class="muted"></div></section><section class="panel"><h2>Le mie richieste</h2><button id="loadMineButton">Aggiorna storico</button><div id="mine" class="muted ticket-history">Accedi per visualizzare lo storico.</div></section></div><section class="panel"><h2>Nuova segnalazione</h2><label>Email di contatto (facoltativa)<input id="ticketEmail" type="email"></label><p class="muted">L’email non viene usata per newsletter. Per ricevere risposte online, accedi o crea un account.</p><div class="two"><label>Oggetto<input id="ticketSubject" maxlength="160"></label><label>Categoria<select id="ticketCategory"><option>Generale</option><option>Installer</option><option>Inject</option><option>Crash</option><option>Traduzione</option><option>Privacy / GDPR</option></select></label></div><label>Descrizione<textarea id="ticketDescription" maxlength="12000"></textarea></label><p class="muted">Non inserire password o token nei log.</p><label>Log opzionale<textarea id="ticketLogs" maxlength="30000"></textarea></label><label class="consent-check"><input id="privacyConsent" type="checkbox"> Acconsento al trattamento dei dati inseriti per gestire questa segnalazione, come descritto nell’informativa privacy.</label><button id="sendTicketButton" class="primary">Invia segnalazione</button><div id="ticketMessage" class="muted"></div></section><script>
const api='/api/v1'; const authEmail=document.getElementById('authEmail'),authPassword=document.getElementById('authPassword'),ticketEmail=document.getElementById('ticketEmail'),ticketSubject=document.getElementById('ticketSubject'),ticketCategory=document.getElementById('ticketCategory'),ticketDescription=document.getElementById('ticketDescription'),ticketLogs=document.getElementById('ticketLogs'),privacyConsent=document.getElementById('privacyConsent'); function token(){return ''} function msg(id,text,ok=false){const e=document.getElementById(id);e.textContent=text;e.className=ok?'success':'error'}
async function register(){const r=await fetch(api+'/auth/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:authEmail.value,password:authPassword.value})});const d=await r.json();if(!r.ok)return msg('authMessage',d.detail||'Registrazione fallita');msg('authMessage','Account creato e accesso effettuato.',true);loadMine()}
async function login(){const r=await fetch(api+'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:authEmail.value,password:authPassword.value})});const d=await r.json();if(!r.ok)return msg('authMessage',d.detail||'Accesso fallito');msg('authMessage','Accesso effettuato.',true);loadMine()}
async function loadMine(){const headers={};if(token())headers.Authorization='Bearer '+token();const r=await fetch(api+'/support/mine',{headers});const d=await r.json();if(!r.ok)return msg('mine',d.detail||'Accedi per visualizzare lo storico.');document.getElementById('mine').innerHTML=d.tickets.length?d.tickets.map(t=>`<div class="panel"><strong>${escapeHtml(t.subject)}</strong><div class="muted">${escapeHtml(t.status)} · ${escapeHtml(t.updated_at)}</div><p>${escapeHtml(t.response||'In attesa di risposta.')}</p></div>`).join(''):'Nessuna segnalazione associata.'}
async function sendTicket(){const body={email:ticketEmail.value,subject:ticketSubject.value,category:ticketCategory.value,description:ticketDescription.value,logs:ticketLogs.value,privacy_consent:privacyConsent.checked};const headers={'Content-Type':'application/json'};if(token())headers.Authorization='Bearer '+token();const r=await fetch(api+'/support/tickets',{method:'POST',headers,body:JSON.stringify(body)});const d=await r.json();if(!r.ok)return msg('ticketMessage',d.detail||'Invio fallito');msg('ticketMessage','Segnalazione inviata: '+d.ticket_id,true);ticketSubject.value='';ticketDescription.value='';ticketLogs.value='';privacyConsent.checked=false;loadMine()}
async function exportData(){const headers={};if(token())headers.Authorization='Bearer '+token();const r=await fetch(api+'/auth/export',{headers});const d=await r.json();if(!r.ok)return msg('authMessage',d.detail||'Accedi prima di scaricare i dati.');const blob=new Blob([JSON.stringify(d,null,2)],{type:'application/json'});const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='interpresona-dati.json';link.click();URL.revokeObjectURL(link.href);msg('authMessage','Export dei dati preparato.',true)}
async function deleteAccount(){const password=prompt('Inserisci la password per confermare l’eliminazione definitiva dell’account.');if(!password)return;const headers={'Content-Type':'application/json'};const r=await fetch(api+'/auth/delete',{method:'POST',headers,body:JSON.stringify({password})});const d=await r.json();if(!r.ok)return msg('authMessage',d.detail||'Accedi prima di eliminare l’account.');msg('authMessage','Account eliminato.',true);loadMine()}
async function logout(){await fetch(api+'/auth/logout',{method:'POST'});msg('authMessage','Sessione chiusa.',true);loadMine()}
function escapeHtml(v){return String(v??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]))}
document.getElementById('registerButton').addEventListener('click',register);document.getElementById('loginButton').addEventListener('click',login);document.getElementById('exportDataButton').addEventListener('click',exportData);document.getElementById('deleteAccountButton').addEventListener('click',deleteAccount);document.getElementById('logoutButton').addEventListener('click',logout);document.getElementById('loadMineButton').addEventListener('click',loadMine);document.getElementById('sendTicketButton').addEventListener('click',sendTicket);loadMine();
</script>""")

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def public_landing_page():
    """Pagina pubblica per gli utenti finali; i pacchetti restano gestiti dall'installer."""
    manifest = get_manifest()
    version = escape(str(manifest.get("version", "2.0.0")))
    patch = escape(str(manifest.get("game_patch", "n/d")))
    updated = escape(str(manifest.get("last_updated", ""))[:10])
    total_files = int(manifest.get("total_files", 0))
    progress = translation_progress()
    ai_percent = f"{progress['ai_percent']:g}"
    human_percent = f"{progress['human_percent']:g}"
    return public_shell("Traduzione italiana per FFXIV", f"""
<section class="hero" aria-labelledby="hero-title">
  <div class="hero-copy">
    <p class="hero-status"><span class="status-dot">Release pronta</span><span class="hero-status-separator">·</span> v{version}</p>
    <p class="eyebrow">TRADUZIONE ITALIANA · FINAL FANTASY XIV</p>
    <h1 id="hero-title">Final Fantasy XIV<br><em>in italiano.</em></h1>
    <p class="lead">Scarica l’installer, estrai lo ZIP, avvia il launcher del tuo sistema e indica la cartella del gioco.</p>
    <div class="actions"><a class="button primary" href="/installer">Scarica l’installer <span aria-hidden="true">↗</span></a><a class="button" href="/status">Vedi la release</a></div>
    <p class="hero-note">Gratuito per uso personale · progetto non commerciale</p>
  </div>
  <aside class="hero-release" aria-label="Riepilogo della release">
    <div class="hero-orbit" aria-hidden="true"><svg viewBox="0 0 180 180" focusable="false"><circle cx="90" cy="90" r="67"/><circle cx="90" cy="90" r="47"/><path d="M90 20v140M20 90h140"/><path d="m90 35 10 45 45 10-45 10-10 45-10-45-45-10 45-10Z"/></svg></div>
    <div class="hero-release-copy"><span class="eyebrow">RELEASE CORRENTE</span><strong>{version}</strong><span>{patch}</span></div>
  </aside>
</section>
<section class="release-strip" aria-label="Riepilogo progetto"><div><span class="eyebrow">COMPATIBILITÀ</span><strong>{patch}</strong></div><div><span class="eyebrow">ULTIMO AGGIORNAMENTO</span><strong>{updated or 'n/d'}</strong></div><div><span class="eyebrow">MODULI PRONTI</span><strong>{total_files}</strong></div><a class="strip-link" href="/status">Vedi stato <span aria-hidden="true">→</span></a></section>
<section id="installer" class="workflow"><div class="section-intro"><p class="number">01 — INSTALLAZIONE</p><h2>Tre passaggi, nessuna modifica manuale.</h2><p class="lead">Non devi conoscere la struttura interna di FFXIV. L’installer fa i controlli e mostra il risultato prima di applicare la traduzione.</p></div><div class="steps"><article class="step"><span class="step-number">01</span><div><h3>Scarica ed estrai</h3><p>Il download è uno ZIP: estrai tutti i file prima di avviare il launcher.</p></div></article><article class="step"><span class="step-number">02</span><div><h3>Avvia il launcher</h3><p>Windows: <code>Interpresona-Installer.bat</code>. Linux: <code>sh Interpresona-Installer.sh</code>. macOS: <code>Interpresona-Installer.command</code>.</p></div></article><article class="step"><span class="step-number">03</span><div><h3>Applica con backup</h3><p>Indica la cartella di FFXIV: la release EXD viene verificata, salvata e installata in modo reversibile.</p></div></article></div><div class="workflow-foot"><span>Il sito distribuisce l’applicazione.</span><span>I file vengono gestiti dall’installer.</span><a href="/status">Controlla la release attuale →</a></div></section>
<section class="contact-band"><div><p class="number">02 — ASSISTENZA</p><h2>Hai bisogno di aiuto?</h2><p>Puoi inviare una segnalazione anche senza account. Con un account opzionale ritrovi storico e risposte in un unico posto.</p></div><div class="actions"><a class="button primary" href="/support">Apri l’assistenza</a><a class="button" href="/about">Come lavoriamo</a></div></section>
<section class="progress-section" aria-label="Avanzamento della traduzione"><div class="section-intro"><p class="number">03 — AVANZAMENTO</p><h2>Stato della traduzione.</h2><p class="lead">La percentuale indica il percorso complessivo: prima la traduzione automatica, poi la revisione umana.</p></div><div class="progress-list"><div class="progress-row"><div class="progress-label"><span>Traduzione automatica</span><strong>{ai_percent}%</strong></div><progress class="progress-meter progress-meter-ai" value="{ai_percent}" max="100">{ai_percent}%</progress></div><div class="progress-row"><div class="progress-label"><span>Revisione umana</span><strong>{human_percent}%</strong></div><progress class="progress-meter progress-meter-human" value="{human_percent}" max="100">{human_percent}%</progress></div></div></section>
<p class="legal-note">FFXIV © SQUARE ENIX CO., LTD. Tutti i diritti riservati.</p>
""")
