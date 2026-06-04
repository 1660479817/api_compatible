#!/usr/bin/env bash
# Layer 2: native protocol surface on source (direct upstream).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE=""
VERBOSE=0
FAMILY=""
EXTRA=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      cat <<'EOF'
Usage: experiment/user-side/scripts/assess-protocol.sh --site SITE [--family NAME]

Layer 2 — Model × wire from assess-plan.json families.<NAME>.
Catalog branch from Layer 1: listed (compare + test) | empty/unavailable (blind test).

Options:
  -v, --verbose   Print per-wire protocol exchange detail
  --family NAME   assess-plan families.<NAME> (gpt | anthropic | other)
  --profile NAME  Deprecated alias for --family
EOF
      exit 0
      ;;
    --site)
      SITE="${2:-}"
      shift 2
      ;;
    -v|--verbose)
      VERBOSE=1
      shift
      ;;
    --family|--profile)
      FAMILY="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

[[ -n "$SITE" ]] || { echo "Error: --site required" >&2; exit 1; }

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

[[ "$VERBOSE" -eq 1 ]] && EXTRA+=(--verbose)
[[ -n "$FAMILY" ]] && EXTRA+=(--family "$FAMILY")
if ((${#EXTRA[@]})); then
  exec python3 "${ROOT}/lib/maas.py" assess-protocol --site "$SITE" "${EXTRA[@]}"
else
  exec python3 "${ROOT}/lib/maas.py" assess-protocol --site "$SITE"
fi
