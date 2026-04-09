#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON_BIN:-/home/jonathan/ai/venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[ERROR] Python no encontrado en: $PYTHON_BIN"
  echo "Define PYTHON_BIN con el intérprete correcto."
  exit 1
fi

echo "[INFO] Usando Python: $PYTHON_BIN"
"$PYTHON_BIN" -m pip install --upgrade pip >/dev/null
"$PYTHON_BIN" -m pip install pyinstaller -r requirements.txt

"$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --clean \
  --name landing-manager \
  --add-data "static:static" \
  landing_manager.py

echo "[OK] Binario Linux generado en: $SCRIPT_DIR/dist/landing-manager/landing-manager"
