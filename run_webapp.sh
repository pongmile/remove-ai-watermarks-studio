#!/usr/bin/env bash
# Launches Remove AI Watermarks Studio on macOS or Linux.
# Usage: ./run_webapp.sh [--host 127.0.0.1] [--port 8000] [--open]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

HOST="${RAIW_HOST:-127.0.0.1}"
PORT="${RAIW_PORT:-8000}"
OPEN_BROWSER=0

usage() {
  cat <<'EOF'
Usage: ./run_webapp.sh [options]

Options:
  --host <addr>   Bind address (default: 127.0.0.1 or $RAIW_HOST)
  --port <num>    Port number (default: 8000 or $RAIW_PORT)
  --open          Open the Studio URL in your browser once ready
  -h, --help      Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="${2:?--host requires a value}"
      shift 2
      ;;
    --port)
      PORT="${2:?--port requires a value}"
      shift 2
      ;;
    --open)
      OPEN_BROWSER=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

export PYTHONUTF8=1
export HF_HUB_DISABLE_XET=1

if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  PY="$SCRIPT_DIR/.venv/bin/python"
elif [[ -x "$SCRIPT_DIR/.venv/Scripts/python.exe" ]]; then
  PY="$SCRIPT_DIR/.venv/Scripts/python.exe"
else
  echo "Virtual environment not found at $SCRIPT_DIR/.venv" >&2
  echo "Run the installer first:  ./install.sh" >&2
  exit 1
fi

URL="http://${HOST}:${PORT}"
echo "Starting Remove AI Watermarks Studio at ${URL}  (Ctrl+C to stop)"

if [[ "$OPEN_BROWSER" -eq 1 ]]; then
  PROBE_HOST="$HOST"
  OPEN_URL="$URL"
  if [[ "$HOST" == "0.0.0.0" ]]; then
    PROBE_HOST="127.0.0.1"
    OPEN_URL="http://127.0.0.1:${PORT}"
  fi
  (
    for _ in $(seq 1 100); do
      if "$PY" -c "import socket, sys; s=socket.socket(); s.settimeout(0.25); sys.exit(0 if s.connect_ex(('${PROBE_HOST}', ${PORT})) == 0 else 1)" 2>/dev/null; then
        if command -v open >/dev/null 2>&1; then
          open "$OPEN_URL" >/dev/null 2>&1 || true
        elif command -v xdg-open >/dev/null 2>&1; then
          xdg-open "$OPEN_URL" >/dev/null 2>&1 || true
        fi
        break
      fi
      sleep 0.25
    done
  ) &
fi

# Invoke the venv Python directly (never `uv run`) to preserve GPU PyTorch wheels.
exec "$PY" -m uvicorn webapp.server:app --host "$HOST" --port "$PORT"
