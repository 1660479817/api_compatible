#!/usr/bin/env bash
# Batch: Layer 1+2 once, then Layer 3 per agent (protocol-scoped by default).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE=""
LAYERS_12=0
PROBE_ONLY=0
SMOKE=0
AGENTS=()
AGENTS_SET=0
FAMILY=""

usage() {
  cat <<'EOF'
Usage: experiment/user-side/scripts/run-user-side-compat.sh --site SITE [options]

Batch: Layer 1 + 2 on source, then Layer 3 per agent.

Options:
  --site ID       Required. sites.json site id
  --layers-12     Only run Layer 1 (platform) + Layer 2 (protocol)
  --probe-only    Layer 3 relay probe per agent (no smoke)
  --smoke         Layer 3 relay probe + Agent smoke per agent
  --agents LIST   Comma-separated: claude,codex,opencode
                  Default: family layer3.agents or all agents across families
  --family NAME   assess-plan families.<NAME> (Layer 2–3 + default agents)
  --profile NAME  Deprecated alias for --family
  -h, --help      Show this help

Examples:
  ./scripts/run-user-side-compat.sh --site b.ai --probe-only
  ./scripts/run-user-side-compat.sh --site b.ai --smoke --agents claude,opencode
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --site)
      SITE="${2:-}"
      shift 2
      ;;
    --layers-12)
      LAYERS_12=1
      shift
      ;;
    --probe-only)
      PROBE_ONLY=1
      shift
      ;;
    --smoke)
      SMOKE=1
      shift
      ;;
    --agents)
      IFS=',' read -r -a AGENTS <<< "${2:-}"
      AGENTS_SET=1
      shift 2
      ;;
    --family|--profile)
      FAMILY="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$SITE" ]]; then
  echo "Error: --site is required" >&2
  usage >&2
  exit 1
fi

if [[ "$LAYERS_12" -eq 0 && "$PROBE_ONLY" -eq 0 && "$SMOKE" -eq 0 ]]; then
  echo "Error: specify --layers-12, --probe-only, or --smoke" >&2
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

if [[ "$AGENTS_SET" -eq 0 ]]; then
  GET_ARGS=(get assess_agents --site "$SITE")
  [[ -n "$FAMILY" ]] && GET_ARGS+=(--family "$FAMILY")
  IFS=',' read -r -a AGENTS <<< "$(python3 "${ROOT}/lib/maas.py" "${GET_ARGS[@]}")"
fi

if [[ "$LAYERS_12" -eq 1 || "$PROBE_ONLY" -eq 1 || "$SMOKE" -eq 1 ]]; then
  ./scripts/assess-platform.sh --site "$SITE"
  echo ""
  PROTO_ARGS=(--site "$SITE")
  [[ -n "$FAMILY" ]] && PROTO_ARGS+=(--family "$FAMILY")
  ./scripts/assess-protocol.sh "${PROTO_ARGS[@]}"
fi

if [[ "$LAYERS_12" -eq 1 ]]; then
  echo "==> Layers 1–2 finished for site=${SITE}"
  exit 0
fi

for agent in "${AGENTS[@]}"; do
  case "$agent" in
    claude|codex|opencode)
      flags=(--site "$SITE" --agent "$agent")
      [[ -n "$FAMILY" ]] && flags+=(--family "$FAMILY")
      if [[ "$PROBE_ONLY" -eq 1 ]]; then
        flags+=(--probe-only)
      fi
      if [[ "$SMOKE" -eq 1 ]]; then
        flags+=(--smoke)
      fi
      ./scripts/run-source-agent-test.sh "${flags[@]}"
      ;;
    *)
      echo "Warning: unknown agent '${agent}', skip" >&2
      ;;
  esac
done

echo "==> Batch finished for site=${SITE} agents=${AGENTS[*]}"
