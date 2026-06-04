#!/usr/bin/env bash
# Shared helpers for Agent launchers: t_claude, t_codex, t_opencode.
# See experiment/user-side/AGENTS.md for directory layout and contribution rules.

set -euo pipefail

MAAS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAAS_PY="${MAAS_ROOT}/lib/maas.py"
MAAS_AGENT="${MAAS_AGENT:-}"

maas_py() {
  python3 "$MAAS_PY" "$@"
}

maas_load_env() {
  if [[ -f "${MAAS_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${MAAS_ROOT}/.env"
    set +a
  fi
  maas_apply_proxy
}

# Use v2rayN / Clash local SOCKS when TUN does not cover the terminal (socks5h = remote DNS).
maas_apply_proxy() {
  if [[ -n "${MAAS_PROXY_SKIP:-}" ]]; then
    return 0
  fi

  local proxy="${MAAS_PROXY:-}"
  if [[ -z "$proxy" ]]; then
    local port
    for port in 10808 10809 7890 1087; do
      if (echo >/dev/tcp/127.0.0.1/"${port}") 2>/dev/null; then
        proxy="socks5h://127.0.0.1:${port}"
        break
      fi
    done
  fi
  [[ -n "$proxy" ]] || return 0

  export ALL_PROXY="$proxy" HTTPS_PROXY="$proxy" HTTP_PROXY="$proxy"
  export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,::1}"
  export NODE_USE_ENV_PROXY=1
}

maas_usage() {
  local agent="${1:-launcher}"
  cat <<EOF
Usage: ./t_${agent} [launcher options] [--] [${agent} args...]

Launcher options:
  --site ID          Upstream site from sites.json (default: interactive or default_site)
  --family NAME      Model family: gpt | anthropic | other (inferred from agent if omitted)
  --model MODEL      Model id (default: assess-plan layer3 for family + agent)
  -y, --yes          Skip interactive prompts; use defaults
  --list-sites       List registered sites
  --list-models      List models from GET /v1/models (--site optional)
  -h, --help         Show this help

Agent traffic always goes through LiteLLM (see scripts/litellm-proxy.sh).
Codex → family gpt; Claude Code → anthropic; OpenCode defaults to gpt on multi-family sites.

Remaining arguments are passed to the underlying CLI.
EOF
}

maas_list_sites() {
  maas_py list-sites
}

maas_list_models() {
  maas_load_env
  local site="${1:-}"
  if [[ -n "$site" ]]; then
    maas_py list-models --site "$site"
  else
    maas_py list-models
  fi
}

maas_default_site() {
  maas_py get default_site
}

maas_pick_site() {
  if [[ -n "${MAAS_SITE:-}" ]]; then
    return 0
  fi
  if [[ "${MAAS_YES:-0}" -eq 1 ]]; then
    MAAS_SITE="$(maas_default_site)"
    return 0
  fi

  _maas_sites=()
  while IFS= read -r line; do
    _maas_sites+=("$line")
  done < <(maas_py list-sites | awk -F'\t' '{print $1}' | sed 's/ (default)//')

  if [[ "${#_maas_sites[@]}" -eq 0 ]]; then
    echo "Error: no sites in sites.json" >&2
    exit 1
  fi
  if [[ "${#_maas_sites[@]}" -eq 1 ]]; then
    MAAS_SITE="${_maas_sites[0]}"
    echo "Site: ${MAAS_SITE}"
    return 0
  fi

  echo "Select site:" >&2
  local i=1
  for s in "${_maas_sites[@]}"; do
    echo "  ${i}) ${s}" >&2
    ((i++)) || true
  done
  local choice
  read -r -p "Choice [1]: " choice </dev/tty
  choice="${choice:-1}"
  if ! [[ "$choice" =~ ^[0-9]+$ ]] || (( choice < 1 || choice > ${#_maas_sites[@]} )); then
    echo "Invalid choice: ${choice}" >&2
    exit 1
  fi
  MAAS_SITE="${_maas_sites[$((choice - 1))]}"
}

maas_resolve_family() {
  local agent="$1"
  if [[ -n "${MAAS_FAMILY:-}" ]]; then
    return 0
  fi
  MAAS_FAMILY="$(maas_py get default_family --site "$MAAS_SITE" --agent "$agent" 2>/dev/null || true)"
  if [[ -z "$MAAS_FAMILY" ]]; then
    echo "Error: cannot infer model family for agent ${agent} on site ${MAAS_SITE}; pass --family" >&2
    exit 1
  fi
  echo "Family: ${MAAS_FAMILY} (inferred for ${agent})" >&2
}

maas_family_args() {
  if [[ -n "${MAAS_FAMILY:-}" ]]; then
    echo --family "$MAAS_FAMILY"
  fi
}

maas_pick_model() {
  local agent="$1"
  maas_resolve_family "$agent"

  if [[ -n "${MAAS_MODEL:-}" ]]; then
    return 0
  fi

  local default
  default="$(maas_py get default_model --site "$MAAS_SITE" --agent "$agent" $(maas_family_args) 2>/dev/null || true)"
  if [[ "${MAAS_YES:-0}" -eq 1 ]]; then
    MAAS_MODEL="${default}"
    if [[ -z "$MAAS_MODEL" ]]; then
      echo "Error: no default model for agent ${agent} family ${MAAS_FAMILY} on site ${MAAS_SITE}" >&2
      exit 1
    fi
    return 0
  fi

  echo "Fetching models from ${MAAS_SITE}..." >&2
  _maas_models=()
  while IFS= read -r line; do
    _maas_models+=("$line")
  done < <(maas_py list-models --site "$MAAS_SITE" 2>/dev/null | head -30 || true)
  if [[ "${#_maas_models[@]}" -eq 0 ]]; then
    if [[ -n "$default" ]]; then
      MAAS_MODEL="$default"
      echo "Using default model: ${MAAS_MODEL}" >&2
      return 0
    fi
    read -r -p "Model id: " MAAS_MODEL </dev/tty
    return 0
  fi

  echo "Select model (or enter custom id):" >&2
  local i=1
  for m in "${_maas_models[@]}"; do
    local mark=""
    [[ "$m" == "$default" ]] && mark=" (default)"
    echo "  ${i}) ${m}${mark}" >&2
    ((i++)) || true
  done
  local choice
  read -r -p "Choice [1]: " choice </dev/tty
  if [[ -z "$choice" ]]; then
    MAAS_MODEL="${_maas_models[0]}"
    return 0
  fi
  if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#_maas_models[@]} )); then
    MAAS_MODEL="${_maas_models[$((choice - 1))]}"
  else
    MAAS_MODEL="$choice"
  fi
}

maas_parse_launcher_args() {
  MAAS_SITE=""
  MAAS_MODEL=""
  MAAS_FAMILY=""
  MAAS_YES=0
  MAAS_PASSTHRU=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --site)
        [[ $# -ge 2 ]] || { echo "Error: --site requires a value" >&2; exit 1; }
        MAAS_SITE="$2"
        shift 2
        ;;
      --family|--profile)
        [[ $# -ge 2 ]] || { echo "Error: --family requires a value" >&2; exit 1; }
        MAAS_FAMILY="$2"
        shift 2
        ;;
      --model)
        [[ $# -ge 2 ]] || { echo "Error: --model requires a value" >&2; exit 1; }
        MAAS_MODEL="$2"
        shift 2
        ;;
      -y|--yes)
        MAAS_YES=1
        shift
        ;;
      --list-sites)
        maas_list_sites
        exit 0
        ;;
      --list-models)
        maas_list_models "${MAAS_SITE:-}"
        exit 0
        ;;
      -h|--help)
        maas_usage "$MAAS_AGENT"
        exit 0
        ;;
      --)
        shift
        MAAS_PASSTHRU=("$@")
        return 0
        ;;
      *)
        MAAS_PASSTHRU+=("$1")
        shift
        ;;
    esac
  done
}

maas_ensure_claude() {
  if command -v claude >/dev/null 2>&1; then
    return 0
  fi
  echo "Claude Code not found; installing..." >&2
  curl -fsSL https://claude.ai/install.sh | bash
  export PATH="${HOME}/.local/bin:${PATH}"
  command -v claude >/dev/null 2>&1 || {
    echo "Error: claude still not on PATH after install" >&2
    exit 1
  }
}

maas_ensure_opencode() {
  if command -v opencode >/dev/null 2>&1; then
    return 0
  fi
  if ! command -v npm >/dev/null 2>&1; then
    echo "Error: npm required to install opencode-ai" >&2
    exit 1
  fi
  echo "OpenCode not found; installing opencode-ai..." >&2
  npm install -g opencode-ai@latest
}

maas_codex_bin() {
  if [[ -n "${CODEX_BIN:-}" && -x "${CODEX_BIN}" ]]; then
    echo "${CODEX_BIN}"
    return 0
  fi
  if command -v codex >/dev/null 2>&1; then
    command -v codex
    return 0
  fi
  local app_bin="/Applications/Codex.app/Contents/Resources/codex"
  if [[ -x "$app_bin" ]]; then
    echo "$app_bin"
    return 0
  fi
  return 1
}

maas_ensure_codex() {
  if maas_codex_bin >/dev/null 2>&1; then
    return 0
  fi
  echo "Error: Codex CLI not found." >&2
  echo "Install Codex.app, set CODEX_BIN in .env, or: brew install --cask openai-codex" >&2
  exit 1
}

maas_write_agent_config() {
  local kind="$1"
  local out="$2"
  local cmd=(write-"${kind}"-config --site "$MAAS_SITE" --out "$out")
  if [[ -n "${MAAS_MODEL:-}" ]]; then
    cmd+=(--model "$MAAS_MODEL")
  fi
  # shellcheck disable=SC2046
  cmd+=($(maas_family_args))
  maas_py "${cmd[@]}"
}

maas_ensure_litellm() {
  if "${MAAS_ROOT}/scripts/litellm-proxy.sh" status --site "$MAAS_SITE" >/dev/null 2>&1; then
    return 0
  fi
  echo "Starting LiteLLM for site=${MAAS_SITE} family=${MAAS_FAMILY:-auto}..." >&2
  local args=(start --site "$MAAS_SITE")
  # shellcheck disable=SC2046
  args+=($(maas_family_args))
  "${MAAS_ROOT}/scripts/litellm-proxy.sh" "${args[@]}"
}

maas_run_claude() {
  MAAS_AGENT="claude"
  maas_load_env
  maas_parse_launcher_args "$@"
  maas_pick_site
  maas_pick_model claude
  maas_ensure_litellm

  local settings="${MAAS_ROOT}/.runtime/claude.litellm.${MAAS_SITE}.json"
  maas_write_agent_config claude "$settings" >/dev/null

  maas_ensure_claude
  echo "→ site=${MAAS_SITE} family=${MAAS_FAMILY} model=${MAAS_MODEL}" >&2
  echo "→ relay=LiteLLM $(maas_py get litellm_relay_base --site "$MAAS_SITE")" >&2
  echo "→ settings=${settings}" >&2

  exec claude --settings "$settings" --model "$MAAS_MODEL" "${MAAS_PASSTHRU[@]}"
}

maas_run_codex() {
  MAAS_AGENT="codex"
  maas_load_env
  maas_parse_launcher_args "$@"
  maas_pick_site
  maas_pick_model codex
  maas_ensure_litellm

  local runtime="${MAAS_ROOT}/.runtime/codex.litellm.${MAAS_SITE}"
  local config_toml="${runtime}/config.toml"
  maas_write_agent_config codex "$config_toml" >/dev/null

  maas_ensure_codex
  local codex_bin
  codex_bin="$(maas_codex_bin)"
  local api_key
  api_key="$(maas_py get litellm_master_key --site "$MAAS_SITE")"

  echo "→ site=${MAAS_SITE} family=${MAAS_FAMILY} model=${MAAS_MODEL}" >&2
  echo "→ relay=LiteLLM $(maas_py get litellm_relay_base --site "$MAAS_SITE")/v1" >&2
  echo "→ config=${config_toml}" >&2

  export CODEX_HOME="$runtime"
  export OPENAI_API_KEY="$api_key"

  exec "$codex_bin" "${MAAS_PASSTHRU[@]}"
}

maas_run_opencode() {
  MAAS_AGENT="opencode"
  maas_load_env
  maas_parse_launcher_args "$@"
  maas_pick_site
  maas_pick_model opencode
  maas_ensure_litellm

  local config="${MAAS_ROOT}/.runtime/opencode.litellm.${MAAS_SITE}.json"
  maas_write_agent_config opencode "$config" >/dev/null

  maas_ensure_opencode

  local oc_model
  # shellcheck disable=SC2046
  oc_model="$(maas_py get opencode_model --site "$MAAS_SITE" $(maas_family_args))"

  echo "→ site=${MAAS_SITE} family=${MAAS_FAMILY} model=${oc_model}" >&2
  echo "→ relay=LiteLLM $(maas_py get litellm_relay_base --site "$MAAS_SITE")/v1" >&2
  echo "→ OPENCODE_CONFIG=${config}" >&2

  export OPENCODE_CONFIG="$config"

  if [[ ${#MAAS_PASSTHRU[@]} -eq 0 ]]; then
    exec opencode -m "$oc_model"
  fi

  local inject_model=0
  case "${MAAS_PASSTHRU[0]}" in
    run) inject_model=1 ;;
  esac

  if [[ $inject_model -eq 0 ]]; then
    exec opencode "${MAAS_PASSTHRU[@]}"
  fi

  local has_model=0
  local arg
  for arg in "${MAAS_PASSTHRU[@]}"; do
    if [[ "$arg" == "-m" || "$arg" == "--model" ]]; then
      has_model=1
      break
    fi
  done
  if [[ $has_model -eq 0 ]]; then
    exec opencode "${MAAS_PASSTHRU[0]}" -m "$oc_model" "${MAAS_PASSTHRU[@]:1}"
  fi
  exec opencode "${MAAS_PASSTHRU[@]}"
}
