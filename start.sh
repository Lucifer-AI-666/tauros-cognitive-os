#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -f .venv/bin/activate ]; then
  echo "Venv assente. Esegui prima ./install.sh" >&2
  exit 1
fi
# shellcheck disable=SC1091
. .venv/bin/activate
HOST="${TAUROS_HOST:-127.0.0.1}"
PORT="${TAUROS_PORT:-8000}"
echo "TAUROS in ascolto su http://${HOST}:${PORT}"
echo "  App PWA  → http://${HOST}:${PORT}/"
echo "  Console  → http://${HOST}:${PORT}/console"
exec uvicorn tauros.api:app --host "$HOST" --port "$PORT"
