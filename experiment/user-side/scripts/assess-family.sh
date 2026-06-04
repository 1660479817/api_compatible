#!/usr/bin/env bash
# One model family: Layer 1 + 2, then Layer 3 (relay + optional smoke) per agent in that family.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE=""
FAMILY=""
PROBE_ONLY=0
SMOKE=0
LAYERS_12=0
WRITE_REPORT=0
VERBOSE=0

usage() {
  cat <<'EOF'
Usage: experiment/user-side/scripts/assess-family.sh --site SITE [--family NAME] [options]

Run Layer 1 (platform) + Layer 2 (protocol) for one model family, then Layer 3
for each agent listed in assess-plan families.<NAME>.layer3.agents.

Options:
  --site ID         Required. sites.json site id
  --family NAME     Model family: gpt | anthropic | other
                    Default: sole family on site, or inferred when unambiguous
  --profile NAME    Deprecated alias for --family
  --layers-12       Only Layer 1 + 2 (no Layer 3)
  --probe-only      Layer 3 relay probe per agent (no smoke)
  --smoke           Layer 3 relay + smoke per agent (default if no L3 mode set)
  --write-report    After batch, run assess-source --write-report for primary Agent
  -v, --verbose     Verbose protocol detail (passed to Layer 1–3 scripts)
  -h, --help

Examples:
  ./scripts/assess-family.sh --site ai.oai.red --family gpt --smoke
  ./scripts/assess-family.sh --site test_gpt_claude --family gpt --probe-only
  ./scripts/assess-family.sh --site b.ai --family anthropic --smoke --write-report
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --site)
      SITE="${2:-}"
      shift 2
      ;;
    --family|--profile)
      FAMILY="${2:-}"
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
    --write-report)
      WRITE_REPORT=1
      shift
      ;;
    -v|--verbose)
      VERBOSE=1
      shift
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
  SMOKE=1
fi

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

cd "$ROOT"

if [[ -z "$FAMILY" ]]; then
  FAM_LIST="$(python3 "${ROOT}/lib/maas.py" get families --site "$SITE")"
  if [[ -z "$FAM_LIST" ]]; then
    echo "Error: site ${SITE} has no families in assess-plan.json" >&2
    exit 1
  fi
  if [[ "$FAM_LIST" != *","* ]]; then
    FAMILY="$FAM_LIST"
    echo "==> Using sole model family: ${FAMILY}"
  else
    echo "Error: site ${SITE} has multiple families (${FAM_LIST}); pass --family" >&2
    exit 1
  fi
fi

PRIMARY="$(python3 "${ROOT}/lib/maas.py" get primary_agent --site "$SITE" --family "$FAMILY" 2>/dev/null || true)"
AGENTS="$(python3 "${ROOT}/lib/maas.py" get assess_agents --site "$SITE" --family "$FAMILY")"

echo "==> assess-family site=${SITE} family=${FAMILY} agents=${AGENTS}"
if [[ -n "$PRIMARY" ]]; then
  echo "==> Primary agent (application scenario): ${PRIMARY}"
fi
echo ""

COMPAT=(./scripts/run-user-side-compat.sh --site "$SITE" --family "$FAMILY")
if [[ "$LAYERS_12" -eq 1 ]]; then
  COMPAT+=(--layers-12)
elif [[ "$PROBE_ONLY" -eq 1 ]]; then
  COMPAT+=(--probe-only)
else
  COMPAT+=(--smoke)
fi

"${COMPAT[@]}"

if [[ "$WRITE_REPORT" -eq 1 ]]; then
  REPORT_AGENT="${PRIMARY:-}"
  if [[ -z "$REPORT_AGENT" ]]; then
    REPORT_AGENT="${AGENTS%%,*}"
  fi
  if [[ ",${AGENTS}," != *",${REPORT_AGENT},"* ]]; then
    REPORT_AGENT="${AGENTS%%,*}"
    echo "==> Warning: primary agent not in family scope; report uses ${REPORT_AGENT}" >&2
  fi
  echo ""
  echo "==> Writing source report (agent=${REPORT_AGENT}, family=${FAMILY})"
  REPORT_ARGS=(./scripts/assess-source.sh --site "$SITE" --family "$FAMILY" --agent "$REPORT_AGENT" --write-report)
  [[ "$SMOKE" -eq 1 ]] && REPORT_ARGS+=(--smoke)
  [[ "$VERBOSE" -eq 1 ]] && REPORT_ARGS+=(-v)
  "${REPORT_ARGS[@]}"
fi

echo ""
echo "==> assess-family finished: site=${SITE} family=${FAMILY}"
