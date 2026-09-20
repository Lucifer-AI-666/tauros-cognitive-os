#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
echo "=== TAUROS install ==="
command -v python3 >/dev/null || { echo "Python 3 non trovato"; exit 1; }
python3 -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
mkdir -p data logs
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Creato .env da .env.example"
fi
echo ""
echo "Installazione OK."
echo "Prossimi passi:"
echo "  source .venv/bin/activate"
echo "  tauros init --owner \"IlTuoNome\" --allowlist \"/path/workspace\""
echo "  # modifica .env (es. TAUROS_GROQ_API_KEY)"
echo "  tauros doctor"
echo "  ./start.sh"
echo "  App:     http://127.0.0.1:8000/"
echo "  Console: http://127.0.0.1:8000/console"
