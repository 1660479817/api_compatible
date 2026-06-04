#!/usr/bin/env bash
# Full source assessment: Layer 1 + 2 + Layer 3 for one Agent.
# Implementation: lib/maas.py assess-source (structured results + optional report).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: experiment/user-side/scripts/assess-source.sh --site SITE --agent AGENT [options]

Run three-layer source assessment (Layer 1–3) via maas.py assess-source.

Options:
  --site ID         sites.json site id
  --agent NAME      claude | codex | opencode (Layer 3)
  --smoke           Layer 3: relay probe + Agent smoke
  --write-report    Write docs/reports/{domain}-源评估报告-{date}.md from results
  --out FILE        Tee stdout/stderr to FILE (shell wrapper only)
  --date DATE       Report date YYYY-MM-DD (default: today)
  -v, --verbose     Print per-wire protocol exchange detail (Layer 1–3)
  --family NAME     assess-plan families.<NAME> (gpt | anthropic | other)
  --profile NAME    Deprecated alias for --family
  -h, --help

Structured JSON is always written to .runtime/<site>-assess-<YYYYMMDD>.json

Examples:
  ./scripts/assess-source.sh --site ai.oai.red --agent opencode --write-report
  ./scripts/assess-source.sh --site ai.oai.red --agent opencode --smoke --write-report
EOF
}

SITE=""
AGENT=""
SMOKE=0
WRITE_REPORT=0
OUT=""
DATE=""
VERBOSE=0
FAMILY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --site) SITE="${2:-}"; shift 2 ;;
    --agent) AGENT="${2:-}"; shift 2 ;;
    --smoke) SMOKE=1; shift ;;
    --write-report) WRITE_REPORT=1; shift ;;
    --out) OUT="${2:-}"; shift 2 ;;
    --date) DATE="${2:-}"; shift 2 ;;
    -v|--verbose) VERBOSE=1; shift ;;
    --family|--profile) FAMILY="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown: $1" >&2; usage >&2; exit 1 ;;
  esac
done

[[ -n "$SITE" && -n "$AGENT" ]] || { usage >&2; exit 1; }

cd "$ROOT"
mkdir -p .runtime

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

ARGS=(assess-source --site "$SITE" --agent "$AGENT")
[[ "$SMOKE" -eq 1 ]] && ARGS+=(--smoke)
[[ "$WRITE_REPORT" -eq 1 ]] && ARGS+=(--write-report)
[[ -n "$DATE" ]] && ARGS+=(--date "$DATE")
[[ "$VERBOSE" -eq 1 ]] && ARGS+=(--verbose)
[[ -n "$FAMILY" ]] && ARGS+=(--family "$FAMILY")

run_assess() {
  python3 "${ROOT}/lib/maas.py" "${ARGS[@]}"
}

if [[ -n "$OUT" ]]; then
  run_assess 2>&1 | tee -a "$OUT"
  exit "${PIPESTATUS[0]}"
else
  run_assess
fi
