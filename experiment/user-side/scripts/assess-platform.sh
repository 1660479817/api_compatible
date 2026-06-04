#!/usr/bin/env bash
# Layer 1: platform link assessment (direct to source).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE=""
VERBOSE=0
EXTRA=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      cat <<'EOF'
Usage: experiment/user-side/scripts/assess-platform.sh --site SITE

Layer 1 — Platform link: GET /v1/models + catalog branch (listed | empty | unavailable).

Options:
  -v, --verbose   Print GET envelope / error detail
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
if ((${#EXTRA[@]})); then
  exec python3 "${ROOT}/lib/maas.py" assess-platform --site "$SITE" "${EXTRA[@]}"
else
  exec python3 "${ROOT}/lib/maas.py" assess-platform --site "$SITE"
fi
