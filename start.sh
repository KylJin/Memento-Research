#!/usr/bin/env bash
# OneManCompany — local service manager
#
# Usage:
#   bash start.sh                    # Start server (runs init wizard if first time)
#   bash start.sh stop               # Stop the running server on the target port
#   bash start.sh restart            # Restart the server on the target port
#   bash start.sh status             # Show whether the target port is in use
#   bash start.sh init               # Run setup wizard only
#   bash start.sh --port 8080        # Override port
#
# Environment:
#   HOST / PORT                       # Server bind (default 0.0.0.0:8000)
#   OPENROUTER_API_KEY                # Required for LLM access

set -euo pipefail
cd "$(dirname "$0")"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
PASSTHROUGH=()

# ---------- helpers ----------
info()  { printf '\033[1;36m▸ %s\033[0m\n' "$*"; }
warn()  { printf '\033[1;33m⚠ %s\033[0m\n' "$*"; }
error() { printf '\033[1;31m✖ %s\033[0m\n' "$*" >&2; exit 1; }

usage() {
  cat <<EOF
Usage: bash start.sh [command] [options]

Commands:
  start      Start the server (default)
  stop       Stop the server running on the target port
  restart    Stop then start the server on the target port
  status     Show whether the target port is in use
  init       Run the setup wizard only

Options:
  --host HOST   Bind host passed through to uvicorn
  --port PORT   Bind port passed through to uvicorn
EOF
}

# ---------- UV detection ----------
ensure_uv() {
  if command -v uv &>/dev/null; then
    return
  fi
  info "Installing UV (fast Python package manager)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv &>/dev/null || error "UV installed but not in PATH. Restart your terminal and try again."
}

# ---------- venv setup ----------
ensure_venv() {
  ensure_uv

  if [ ! -d .venv ]; then
    info "Creating Python virtual environment (via UV)..."
    uv venv --python 3.12
  fi

  # shellcheck disable=SC1091
  source .venv/bin/activate
  info "Installing dependencies..."
  uv pip install -e . -q
}

run_init() {
  ensure_venv
  info "Running setup wizard..."
  exec .venv/bin/onemancompany-init "$@"
}

_init_is_complete() {
  # Check that key files/dirs exist within .onemancompany/
  [ -d .onemancompany ] \
    && [ -f .onemancompany/.env ] \
    && [ -d .onemancompany/company/human_resource/employees ]
}

listener_pids() {
  lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true
}

stop_backend() {
  local pids
  pids=$(listener_pids)
  if [ -z "$pids" ]; then
    info "No backend running on :$PORT"
    return 0
  fi

  info "Stopping backend on :$PORT (PIDs: $pids)"
  echo "$pids" | xargs kill -TERM 2>/dev/null || true

  for _ in $(seq 1 20); do
    if [ -z "$(listener_pids)" ]; then
      info "Backend stopped"
      return 0
    fi
    sleep 0.5
  done

  warn "Backend still running after SIGTERM, forcing shutdown"
  echo "$pids" | xargs kill -9 2>/dev/null || true
  sleep 1
}

status_backend() {
  local pids
  pids=$(listener_pids)
  if [ -z "$pids" ]; then
    info "Backend is not running on :$PORT"
    return 1
  fi

  info "Backend is listening on :$PORT"
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN
}

run_server() {
  ensure_venv

  if ! _init_is_complete; then
    if [ -d .onemancompany ]; then
      warn ".onemancompany/ exists but is incomplete — re-running setup wizard"
    else
      warn ".onemancompany/ not found — launching setup wizard first"
    fi
    .venv/bin/onemancompany-init
  fi

  if [ -n "$(listener_pids)" ]; then
    error "Port $PORT is already in use. Run 'bash start.sh restart --port $PORT' or 'bash start.sh stop --port $PORT'."
  fi

  info "Starting OneManCompany..."
  export HOST PORT
  exec .venv/bin/onemancompany "$@"
}

# ---------- entry ----------
COMMAND="start"

case "${1:-}" in
  start|stop|restart|status|init)
    COMMAND="$1"
    shift
    ;;
  --help|-h)
    usage
    exit 0
    ;;
esac

while [ $# -gt 0 ]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --port)
      [ $# -ge 2 ] || error "--port requires a value"
      PORT="$2"
      PASSTHROUGH+=("$1" "$2")
      shift 2
      ;;
    --port=*)
      PORT="${1#*=}"
      PASSTHROUGH+=("$1")
      shift
      ;;
    --host)
      [ $# -ge 2 ] || error "--host requires a value"
      HOST="$2"
      PASSTHROUGH+=("$1" "$2")
      shift 2
      ;;
    --host=*)
      HOST="${1#*=}"
      PASSTHROUGH+=("$1")
      shift
      ;;
    *)
      PASSTHROUGH+=("$1")
      shift
      ;;
  esac
done

case "$COMMAND" in
  start)
    run_server "${PASSTHROUGH[@]}"
    ;;
  stop)
    stop_backend
    ;;
  restart)
    stop_backend
    run_server "${PASSTHROUGH[@]}"
    ;;
  status)
    status_backend
    ;;
  init)
    run_init "${PASSTHROUGH[@]}"
    ;;
esac
