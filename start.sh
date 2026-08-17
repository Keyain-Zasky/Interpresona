#!/bin/bash
# Script di avvio per FFXIV Zero-Error Translator Suite

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR/app" || exit

# La copia Codex non include il venv del progetto originale. Usa quello locale
# se presente, altrimenti lascia che l'ambiente Python corrente risolva uvicorn.
if [ -f "$DIR/app/venv/bin/activate" ]; then
    source "$DIR/app/venv/bin/activate"
fi

echo "========================================="
echo " FFXIV Zero-Error Translator Suite"
echo "========================================="
echo ""
echo "Avvio del server backend in corso..."
echo "L'interfaccia grafica sarà disponibile su:"
PORT="${PORT:-8000}"
echo "👉 http://127.0.0.1:$PORT"
echo ""
echo "Premi CTRL+C per spegnere il server."
echo "========================================="
echo ""

# La copia ufficiale non include un virtualenv nel repository. Usa quello
# condiviso dall'ambiente locale quando Python di sistema non ha Uvicorn.
PYTHON_BIN="${PYTHON_BIN:-python}"
if ! "$PYTHON_BIN" -c 'import uvicorn' >/dev/null 2>&1; then
    SHARED_PYTHON="/home/keyain/.gemini/antigravity/brain/cfbf4fe9-a1bf-4c55-9a3e-fc1f6a38f4db/app/venv/bin/python"
    if [ -x "$SHARED_PYTHON" ] && "$SHARED_PYTHON" -c 'import uvicorn' >/dev/null 2>&1; then
        PYTHON_BIN="$SHARED_PYTHON"
    else
        echo "Errore: Uvicorn non è installato nell'ambiente Python disponibile."
        echo "Installa le dipendenze oppure imposta PYTHON_BIN con un Python che includa FastAPI e Uvicorn."
        exit 1
    fi
fi

echo "Python server: $PYTHON_BIN"
exec "$PYTHON_BIN" -m uvicorn main:app --host 127.0.0.1 --port "$PORT"
