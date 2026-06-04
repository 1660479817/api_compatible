#!/usr/bin/env bash
# P1 smoke: mock New API + MySQL token lookup + corpus-tap capture.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PATH="/opt/homebrew/bin:${PATH:-}"

echo "==> unit + e2e (Go)"
go test ./...

echo "==> docker smoke stack"
docker compose -f deploy/docker-compose.smoke.yml up -d --build --wait

TAP_URL="${CORPUS_TAP_SMOKE_URL:-http://127.0.0.1:18443}"
TOKEN="sk-integration-active"

echo "==> readyz"
curl -sfS "$TAP_URL/readyz" >/dev/null

echo "==> POST /v1/messages"
curl -sfS -X POST "$TAP_URL/v1/messages" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-smoke","max_tokens":8,"messages":[{"role":"user","content":"ping"}]}' >/dev/null

sleep 2

echo "==> stats"
curl -sfS -H "X-Corpus-Admin-Key: smoke-admin" "$TAP_URL/internal/stats?user_id=100" | tee /dev/stderr
echo

echo "==> integration token test"
export CORPUS_TAP_TEST_MYSQL_DSN='root:corpus@tcp(127.0.0.1:13306)/newapi?parseTime=true'
go test -tags=integration ./internal/enrich/ -count=1

echo "==> OK"
docker compose -f deploy/docker-compose.smoke.yml down
