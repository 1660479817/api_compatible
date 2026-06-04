#!/usr/bin/env bash
# LiteLLM relay: upstream source → local proxy (metering + protocol conversion) → Agent.
# See docs/experiment/EC2-用户侧隔离实验点设计.md §2.3 / §3.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE=""
PORT=0
FAMILY=""

usage() {
  cat <<'EOF'
Usage: experiment/user-side/scripts/litellm-proxy.sh {start|stop|status|write-config} --site SITE

Manage LiteLLM proxy for a sites.json upstream (Agent-facing relay).

Commands:
  start         Generate config (if needed) and start proxy in background
  stop          Stop proxy for the site
  status        Print pid / health
  write-config  Regenerate .runtime/litellm.<site>.yaml only

Options:
  --site ID     Required. sites.json site id
  --port N      Override listen port (default: sites.json litellm.port or 4000)
  --family NAME   assess-plan families.<NAME> for LiteLLM model_list
  --profile NAME  Deprecated alias for --family
  -h, --help    Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --site)
      SITE="${2:-}"
      shift 2
      ;;
    --port)
      PORT="${2:-0}"
      shift 2
      ;;
    --family|--profile)
      FAMILY="${2:-}"
      shift 2
      ;;
    start|stop|status|write-config)
      CMD="$1"
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "${CMD:-}" ]]; then
  echo "Error: command required (start|stop|status|write-config)" >&2
  usage >&2
  exit 1
fi

if [[ -z "$SITE" ]]; then
  echo "Error: --site is required" >&2
  usage >&2
  exit 1
fi

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

cd "$ROOT"

CONFIG="${ROOT}/.runtime/litellm.${SITE}.yaml"
PID_FILE="${ROOT}/.runtime/litellm.${SITE}.pid"
LOG_FILE="${ROOT}/.runtime/litellm.${SITE}.log"
mkdir -p .runtime

if [[ "$PORT" -eq 0 ]]; then
  PORT="$(python3 "${ROOT}/lib/maas.py" get litellm_port --site "$SITE")"
fi

write_config() {
  local args=(write-litellm-config --site "$SITE" --out "$CONFIG")
  if [[ "$PORT" -ne 0 ]]; then
    args+=(--port "$PORT")
  fi
  if [[ -n "$FAMILY" ]]; then
    args+=(--family "$FAMILY")
  fi
  python3 "${ROOT}/lib/maas.py" "${args[@]}"
}

case "$CMD" in
  write-config)
    write_config
    echo "Config: ${CONFIG}"
    ;;
  stop)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      kill "$(cat "$PID_FILE")" 2>/dev/null || true
      rm -f "$PID_FILE"
      echo "Stopped LiteLLM for site=${SITE}"
    else
      echo "LiteLLM not running for site=${SITE}"
    fi
    ;;
  status)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "running pid=$(cat "$PID_FILE") port=${PORT} config=${CONFIG}"
      curl -sf "http://127.0.0.1:${PORT}/health/liveliness" >/dev/null && echo "health=ok" || echo "health=unknown"
    else
      echo "stopped site=${SITE}"
      exit 1
    fi
    ;;
  start)
    write_config
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      kill "$(cat "$PID_FILE")" 2>/dev/null || true
      rm -f "$PID_FILE"
    fi
    # Stale proxies often survive pid-file cleanup (manual restarts, crashed workers).
    if command -v lsof >/dev/null 2>&1; then
      while read -r pid; do
        [[ -n "$pid" ]] || continue
        kill "$pid" 2>/dev/null || true
      done < <(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null || true)
      sleep 1
    fi
    KEY_ENV="$(python3 "${ROOT}/lib/maas.py" get api_key_env --site "$SITE")"
    if [[ -z "${!KEY_ENV:-}" ]]; then
      echo "Error: ${KEY_ENV} is not set (source .env)" >&2
      exit 1
    fi
    if ! python3 -c "import litellm" 2>/dev/null; then
      echo "Installing litellm[proxy]..." >&2
      pip3 install 'litellm[proxy]' >&2
    fi
    nohup env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u MAAS_PROXY \
      "${KEY_ENV}=${!KEY_ENV}" \
      python3 -m litellm.proxy.proxy_cli --config "$CONFIG" --port "$PORT" \
      >"$LOG_FILE" 2>&1 &
    echo $! >"$PID_FILE"
    for _ in $(seq 1 30); do
      if curl -sf "http://127.0.0.1:${PORT}/health/liveliness" >/dev/null 2>&1; then
        echo "LiteLLM ready site=${SITE} http://127.0.0.1:${PORT} log=${LOG_FILE}"
        exit 0
      fi
      sleep 1
    done
    echo "LiteLLM failed to start; see ${LOG_FILE}" >&2
    tail -20 "$LOG_FILE" >&2 || true
    exit 1
    ;;
esac
