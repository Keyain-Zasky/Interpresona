#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
else
    echo "Python 3 non è installato. Installa Python 3.10 o superiore e riprova."
    printf 'Premi Invio per chiudere... '
    read -r _
    exit 1
fi
if [ "$#" -eq 0 ]; then
    exec "$PYTHON" "$SCRIPT_DIR/interpresona_gui.py"
fi
exec "$PYTHON" "$SCRIPT_DIR/interpresona_installer.py" "$@"
