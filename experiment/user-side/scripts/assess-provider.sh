#!/usr/bin/env bash
# Provider profile assessment: direct API checks without LiteLLM / Agent E2E.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${ROOT}/provider-profiles.json"
ARGS=()

usage() {
  cat <<'EOF'
Usage: experiment/user-side/scripts/assess-provider.sh [options]

Assess third-party provider profiles from provider-profiles.json.

Options:
  --config PATH          Provider profile config JSON
  --platform ID          Only assess one platform_id
  --provider-profile ID  Only assess one profile id
  --repeat N             Sequential reliability repeat count
  --concurrency N        Optional concurrent request count
  --timeout SEC          Per request timeout seconds
  --cache-check          Run optional GPT/Claude cache behavior observation
  --write-report         Write docs/reports/{platform}-平台评估报告-{date}.md
  --json                 Print full JSON result
  -h, --help             Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --config)
      CONFIG="${2:-}"
      shift 2
      ;;
    --platform|--provider-profile|--repeat|--concurrency|--timeout)
      ARGS+=("$1" "${2:-}")
      shift 2
      ;;
    --cache-check|--write-report|--json)
      ARGS+=("$1")
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

exec python3 "${ROOT}/lib/maas.py" assess-provider --config "$CONFIG" "${ARGS[@]}"
