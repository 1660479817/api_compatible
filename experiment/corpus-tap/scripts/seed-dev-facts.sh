#!/usr/bin/env bash
# Insert one Anthropic-shaped http_exchange + local blobs for offline profile dev.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

: "${CORPUS_TAP_DATABASE_URL:?set CORPUS_TAP_DATABASE_URL}"
DATA_DIR="${CORPUS_TAP_LOCAL_DATA_DIR:-$ROOT/data}"
mkdir -p "$DATA_DIR"

export CORPUS_TAP_DEV_DEPLOYMENT_ID="${CORPUS_TAP_DEV_DEPLOYMENT_ID:-550e8400-e29b-41d4-a716-446655440000}"
export CORPUS_TAP_DEV_EXCHANGE_ID="${CORPUS_TAP_DEV_EXCHANGE_ID:-660e8400-e29b-41d4-a716-446655440001}"
export CORPUS_TAP_DEV_USER_ID="${CORPUS_TAP_DEV_USER_ID:-100}"

eval "$(python3 - "$DATA_DIR" <<'PY'
import gzip
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

data_dir = Path(sys.argv[1])
deploy_id = os.environ["CORPUS_TAP_DEV_DEPLOYMENT_ID"]
exchange_id = os.environ["CORPUS_TAP_DEV_EXCHANGE_ID"]
user_id = int(os.environ["CORPUS_TAP_DEV_USER_ID"])
now = datetime.now(timezone.utc)
dt = now.strftime("%Y-%m-%d")

req = {
    "model": "claude-dev",
    "max_tokens": 128,
    "messages": [
        {
            "role": "user",
            "content": (
                "Explain briefly how HTTP caching works for REST APIs, "
                "including Cache-Control and ETag."
            ),
        }
    ],
}
resp = {
    "id": "msg_dev_seed",
    "type": "message",
    "role": "assistant",
    "content": [
        {
            "type": "text",
            "text": (
                "HTTP caching lets clients reuse responses. Cache-Control "
                "directives such as max-age define freshness; ETag supports "
                "conditional GET with If-None-Match."
            ),
        }
    ],
}


def write_gz(role: str, payload: bytes) -> tuple[str, str, int]:
    prefix = f"{deploy_id}/user_id={user_id}/dt={dt}/{exchange_id}"
    name = (
        "upstream_response.json.gz"
        if role == "upstream_response"
        else "client_request.json.gz"
    )
    path = data_dir / prefix / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(payload))
    return f"file://{path}", hashlib.sha256(payload).hexdigest(), len(payload)


req_bytes = json.dumps(req).encode()
resp_bytes = json.dumps(resp).encode()
req_uri, req_sha, req_len = write_gz("client_request", req_bytes)
resp_uri, resp_sha, resp_len = write_gz("upstream_response", resp_bytes)

print(f"REQ_URI={req_uri}")
print(f"RESP_URI={resp_uri}")
print(f"REQ_SHA={req_sha}")
print(f"RESP_SHA={resp_sha}")
print(f"REQ_LEN={req_len}")
print(f"RESP_LEN={resp_len}")
PY
)"

psql "$CORPUS_TAP_DATABASE_URL" -v ON_ERROR_STOP=1 \
  -v deploy_id="$CORPUS_TAP_DEV_DEPLOYMENT_ID" \
  -v ex_id="$CORPUS_TAP_DEV_EXCHANGE_ID" \
  -v user_id="$CORPUS_TAP_DEV_USER_ID" \
  -v req_uri="$REQ_URI" \
  -v resp_uri="$RESP_URI" \
  -v req_sha="$REQ_SHA" \
  -v resp_sha="$RESP_SHA" \
  -v req_len="$REQ_LEN" \
  -v resp_len="$RESP_LEN" <<'SQL'
INSERT INTO tap_deployment (id, newapi_image, tap_image)
VALUES (:'deploy_id'::uuid, 'dev-seed', 'corpus-tap')
ON CONFLICT (id) DO NOTHING;

INSERT INTO http_exchange (
  id, deployment_id, user_id, tap_request_id, endpoint, wire, is_stream,
  status_code, latency_ms, model_name, client_bytes, response_bytes,
  client_request_uri, upstream_response_uri,
  client_request_sha256, upstream_response_sha256
) VALUES (
  :'ex_id'::uuid,
  :'deploy_id'::uuid,
  :user_id,
  'dev-seed-1',
  '/v1/messages',
  'anthropic_messages',
  false,
  200,
  42,
  'claude-dev',
  :req_len,
  :resp_len,
  :'req_uri',
  :'resp_uri',
  :'req_sha',
  :'resp_sha'
)
ON CONFLICT (id) DO NOTHING;
SQL

echo "seeded exchange $CORPUS_TAP_DEV_EXCHANGE_ID user_id=$CORPUS_TAP_DEV_USER_ID under $DATA_DIR"
