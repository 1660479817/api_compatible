#!/usr/bin/env bash
# Layer 3: Source → LiteLLM → Agent (relay probe + optional smoke).
# Terminology: Layer 3 = assessment tier; L3/L4 = E2E depth inside smoke.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE=""
AGENT=""
PROBE_ONLY=0
SMOKE=0
VERBOSE=0
FAMILY=""

usage() {
  cat <<'EOF'
Usage: experiment/user-side/scripts/run-source-agent-test.sh --site SITE --agent AGENT [options]

Layer 3 — upstream source → LiteLLM → specified Agent.

Required:
  --site ID       sites.json site id (upstream source)
  --agent NAME    claude | codex | opencode (must be in family scope)

Options:
  --probe-only    Layer 3 relay wire probe only (E2E L2 via LiteLLM)
  --smoke         relay probe + t_* non-interactive smoke (E2E L3+)
  -v, --verbose   Print relay protocol exchange detail (--probe-only)
  --family NAME   assess-plan families.<NAME>
  --profile NAME  Deprecated alias for --family
  -h, --help      Show this help

Examples:
  ./scripts/run-source-agent-test.sh --site b.ai --agent codex --probe-only
  ./scripts/run-source-agent-test.sh --site b.ai --agent claude --smoke
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --site)
      SITE="${2:-}"
      shift 2
      ;;
    --agent)
      AGENT="${2:-}"
      shift 2
      ;;
    --probe-only)
      PROBE_ONLY=1
      shift
      ;;
    --smoke)
      SMOKE=1
      shift
      ;;
    -v|--verbose)
      VERBOSE=1
      shift
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

if [[ -z "$SITE" || -z "$AGENT" ]]; then
  echo "Error: --site and --agent are required" >&2
  usage >&2
  exit 1
fi

case "$AGENT" in
  claude|codex|opencode) ;;
  *)
    echo "Error: --agent must be claude, codex, or opencode" >&2
    exit 1
    ;;
esac

if [[ "$PROBE_ONLY" -eq 0 && "$SMOKE" -eq 0 ]]; then
  echo "Error: specify --probe-only and/or --smoke" >&2
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

if [[ -z "$FAMILY" ]]; then
  FAMILY="$(python3 "${ROOT}/lib/maas.py" get default_family --site "$SITE" --agent "$AGENT" 2>/dev/null || true)"
fi
GET_ARGS=(get assess_agents --site "$SITE")
[[ -n "$FAMILY" ]] && GET_ARGS+=(--family "$FAMILY")
IN_SCOPE="$(python3 "${ROOT}/lib/maas.py" "${GET_ARGS[@]}")"
if [[ ",${IN_SCOPE}," != *",${AGENT},"* ]]; then
  echo "Error: agent '${AGENT}' not in scope for site '${SITE}' (in scope: ${IN_SCOPE})" >&2
  exit 1
fi

echo "==> Starting LiteLLM relay for site=${SITE}"
LITELLM_ARGS=(start --site "$SITE")
[[ -n "$FAMILY" ]] && LITELLM_ARGS+=(--family "$FAMILY")
./scripts/litellm-proxy.sh "${LITELLM_ARGS[@]}"

echo "==> Layer 3 relay probe: site=${SITE} agent=${AGENT}"
PROBE_ARGS=(probe-relay --site "$SITE" --agent "$AGENT")
[[ "$VERBOSE" -eq 1 ]] && PROBE_ARGS+=(--verbose)
[[ -n "$FAMILY" ]] && PROBE_ARGS+=(--family "$FAMILY")
python3 "${ROOT}/lib/maas.py" "${PROBE_ARGS[@]}"

if [[ "$PROBE_ONLY" -eq 1 && "$SMOKE" -eq 0 ]]; then
  echo "==> Done (--probe-only)"
  exit 0
fi

if [[ "$SMOKE" -eq 0 ]]; then
  exit 0
fi

echo "==> Layer 3 smoke scenarios: site=${SITE} agent=${AGENT}"
SMOKE_ARGS=(run-smoke --site "$SITE" --agent "$AGENT")
[[ -n "$FAMILY" ]] && SMOKE_ARGS+=(--family "$FAMILY")
python3 "${ROOT}/lib/maas.py" "${SMOKE_ARGS[@]}"

echo "==> Smoke finished: site=${SITE} agent=${AGENT}"
