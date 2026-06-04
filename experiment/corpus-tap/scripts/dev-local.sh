#!/usr/bin/env bash
# Local dev: seed one fact row, run one profile batch, print summary.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export CORPUS_TAP_DATABASE_URL="${CORPUS_TAP_DATABASE_URL:-postgres://corpus:corpus@127.0.0.1:5432/corpus?sslmode=disable}"
export CORPUS_TAP_LOCAL_DATA_DIR="${CORPUS_TAP_LOCAL_DATA_DIR:-$ROOT/data}"

export CORPUS_PROFILE_DATABASE_URL="${CORPUS_PROFILE_DATABASE_URL:-$CORPUS_TAP_DATABASE_URL}"
export CORPUS_PROFILE_LOCAL_DATA_DIR="${CORPUS_PROFILE_LOCAL_DATA_DIR:-$CORPUS_TAP_LOCAL_DATA_DIR}"
export CORPUS_PROFILE_LLM_BASE="${CORPUS_PROFILE_LLM_BASE:-http://127.0.0.1:4000}"
export CORPUS_PROFILE_LLM_API_KEY="${CORPUS_PROFILE_LLM_API_KEY:-sk-operator-analysis}"
export CORPUS_PROFILE_LLM_MODEL_L1="${CORPUS_PROFILE_LLM_MODEL_L1:-gpt-4o-mini}"
export CORPUS_PROFILE_LLM_MODEL_L2="${CORPUS_PROFILE_LLM_MODEL_L2:-gpt-4o-mini}"
export CORPUS_PROFILE_ADMIN_KEY="${CORPUS_PROFILE_ADMIN_KEY:-dev-profile-admin}"
export CORPUS_PROFILE_LISTEN="${CORPUS_PROFILE_LISTEN:-127.0.0.1:8444}"

chmod +x scripts/seed-dev-facts.sh
./scripts/seed-dev-facts.sh

make build-profile
./bin/corpus-profile &
PID=$!
trap 'kill $PID 2>/dev/null || true' EXIT
sleep 1

if [[ "$CORPUS_PROFILE_LISTEN" == :* ]]; then
  LISTEN_HOST="127.0.0.1${CORPUS_PROFILE_LISTEN}"
else
  LISTEN_HOST="$CORPUS_PROFILE_LISTEN"
fi
curl -sfS -X POST -H "X-Corpus-Admin-Key: $CORPUS_PROFILE_ADMIN_KEY" \
  "http://$LISTEN_HOST/internal/run"

sleep 8

echo "==> exchange_quality"
psql "$CORPUS_TAP_DATABASE_URL" -c \
  "SELECT exchange_id, gate_passed, tier, llm_status FROM exchange_quality ORDER BY updated_at DESC LIMIT 5;"

echo "==> user_profile"
psql "$CORPUS_TAP_DATABASE_URL" -c \
  "SELECT user_id, cohort, user_quality_score FROM user_profile ORDER BY updated_at DESC LIMIT 5;"

echo "dev-local done (profile PID $PID stopped on exit)"
