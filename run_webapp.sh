#!/usr/bin/env bash
# Smart launcher for Remove AI Watermarks Studio on macOS or Linux.
# Supports single-instance browser reuse, auto-shutdown when last tab closes,
# and seamless in-app restart (exit code 75).
#
# Usage: ./run_webapp.sh [--host 127.0.0.1] [--port 8000] [--open] [--no-auto-shutdown]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

HOST="${RAIW_HOST:-127.0.0.1}"
PORT="${RAIW_PORT:-8000}"
OPEN_BROWSER=0
NO_AUTO_SHUTDOWN=0

usage() {
  cat <<'EOF'
Usage: ./run_webapp.sh [options]

Options:
  --host <addr>       Bind address (default: 127.0.0.1 or $RAIW_HOST)
  --port <num>        Port number (default: 8000 or $RAIW_PORT)
  --open              Open the Studio URL in your browser once ready
  --no-auto-shutdown  Keep server running even after all browser tabs close
  -h, --help          Show this help message
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
    --no-auto-shutdown)
      NO_AUTO_SHUTDOWN=1
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
export RAIW_ALLOW_RESTART=1
if [[ "$NO_AUTO_SHUTDOWN" -eq 1 ]]; then
  export RAIW_AUTO_SHUTDOWN=0
elif [[ "$OPEN_BROWSER" -eq 1 && -z "${RAIW_AUTO_SHUTDOWN:-}" ]]; then
  export RAIW_AUTO_SHUTDOWN=1
fi

if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  PY="$SCRIPT_DIR/.venv/bin/python"
elif [[ -x "$SCRIPT_DIR/.venv/Scripts/python.exe" ]]; then
  PY="$SCRIPT_DIR/.venv/Scripts/python.exe"
else
  echo "Virtual environment not found at $SCRIPT_DIR/.venv" >&2
  echo "Run the installer first:  ./install.sh" >&2
  exit 1
fi

PROBE_HOST="$HOST"
if [[ "$HOST" == "0.0.0.0" ]]; then
  PROBE_HOST="127.0.0.1"
fi
OPEN_URL="http://${PROBE_HOST}:${PORT}"
URL="http://${HOST}:${PORT}"

open_url() {
  if command -v open >/dev/null 2>&1; then
    open "$1" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$1" >/dev/null 2>&1 || true
  fi
}

# Smart single-instance check: if Studio is already running, reuse it instead of crashing
if "$PY" -c "import urllib.request, sys; r = urllib.request.urlopen('${OPEN_URL}/health', timeout=1); sys.exit(0 if r.status == 200 else 1)" 2>/dev/null; then
  echo "Remove AI Watermarks Studio is already running at ${OPEN_URL}"
  if [[ "$OPEN_BROWSER" -eq 1 ]]; then
    open_url "$OPEN_URL"
  fi
  exit 0
fi

echo "Starting Remove AI Watermarks Studio at ${URL}  (click Quit in app or Ctrl+C to stop)"

if [[ "$OPEN_BROWSER" -eq 1 ]]; then
  (
    for _ in $(seq 1 100); do
      if "$PY" -c "import socket, sys; s=socket.socket(); s.settimeout(0.25); sys.exit(0 if s.connect_ex(('${PROBE_HOST}', ${PORT})) == 0 else 1)" 2>/dev/null; then
        open_url "$OPEN_URL"
        break
      fi
      sleep 0.25
    done
  ) &
fi

# Invoke the venv Python directly (never `uv run`) to preserve GPU PyTorch wheels.
while true; do
  set +e
  "$PY" -m uvicorn webapp.server:app --host "$HOST" --port "$PORT"
  RC=$?
  set -e
  if [[ "$RC" -eq 75 ]]; then
    echo "Restarting Remove AI Watermarks Studio..."
    continue
  fi
  exit "$RC"
done
