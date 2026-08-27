#!/bin/sh
# Script di avvio per FFXIV Zero-Error Translator Suite.
# Funziona sia con `bash start.sh` sia con `sh start.sh`.

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd) || exit 1
APP_DIR="$PROJECT_DIR/app"
REQUIREMENTS_FILE="$PROJECT_DIR/server/requirements.txt"
[ -f "$APP_DIR/main.py" ] || { echo "Errore: backend non trovato in $APP_DIR"; exit 1; }
cd "$APP_DIR" || exit 1

echo "========================================="
echo " FFXIV Zero-Error Translator Suite"
echo "========================================="
echo ""
echo "Avvio del server backend in corso..."
echo "L'interfaccia grafica sarà disponibile su:"
PORT="${PORT:-8000}"
echo "👉 http://127.0.0.1:$PORT"
echo "Progetto: $PROJECT_DIR"
echo ""
echo "Premi CTRL+C per spegnere il server."
echo "========================================="
echo ""

# Cerca un ambiente che contenga entrambe le dipendenze del backend.
PYTHON_CANDIDATES="${PYTHON_BIN:-}"
PYTHON_CANDIDATES="$PYTHON_CANDIDATES
$PROJECT_DIR/.venv/bin/python
$(command -v python3 2>/dev/null || true)
$(command -v python 2>/dev/null || true)"

PYTHON_BIN=""
while IFS= read -r candidate; do
    [ -n "$candidate" ] || continue
    [ -x "$candidate" ] || continue
    if "$candidate" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        break
    fi
done <<EOF
$PYTHON_CANDIDATES
EOF

if [ -z "$PYTHON_BIN" ] && command -v python3 >/dev/null 2>&1; then
    LOCAL_VENV="$PROJECT_DIR/.venv"
    BOOTSTRAP_PYTHON=$(command -v python3)
    echo "Dipendenze non trovate: preparo un ambiente Python locale in $LOCAL_VENV..."
    if "$BOOTSTRAP_PYTHON" -m venv "$LOCAL_VENV" && \
       PIP_DISABLE_PIP_VERSION_CHECK=1 "$LOCAL_VENV/bin/python" -m pip install --disable-pip-version-check -r "$REQUIREMENTS_FILE" >/dev/null; then
        if "$LOCAL_VENV/bin/python" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
            PYTHON_BIN="$LOCAL_VENV/bin/python"
        fi
    fi
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "Errore: FastAPI/Uvicorn non sono installati in nessun Python disponibile."
    echo "Controlla la connessione oppure imposta PYTHON_BIN=/percorso/python."
    exit 1
fi

if "$PYTHON_BIN" - "$PORT" <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
    raise SystemExit(0 if probe.connect_ex(("127.0.0.1", port)) == 0 else 1)
PY
then
    echo "Errore: la porta $PORT è già occupata."
    echo "Chiudi il server esistente oppure avvia con PORT=18999 sh start.sh."
    exit 1
fi

echo "Python server: $PYTHON_BIN"
exec "$PYTHON_BIN" -m uvicorn main:app --host 127.0.0.1 --port "$PORT"
