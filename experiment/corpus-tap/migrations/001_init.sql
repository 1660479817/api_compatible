-- Corpus Tap metadata schema (see experiment/corpus-tap/DESIGN.md §10)

CREATE TABLE IF NOT EXISTS tap_deployment (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  newapi_image TEXT NOT NULL DEFAULT '',
  tap_image TEXT NOT NULL DEFAULT 'corpus-tap',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS http_exchange (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  deployment_id UUID REFERENCES tap_deployment(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  retention_until TIMESTAMPTZ,
  user_id INT NOT NULL,
  token_id INT,
  tap_request_id VARCHAR(64) NOT NULL,
  newapi_request_id VARCHAR(64),
  upstream_request_id VARCHAR(128),
  session_key TEXT,
  endpoint TEXT NOT NULL,
  wire TEXT NOT NULL,
  is_stream BOOLEAN NOT NULL DEFAULT false,
  status_code INT,
  latency_ms INT,
  model_name TEXT,
  client_bytes BIGINT,
  response_bytes BIGINT,
  client_request_uri TEXT,
  upstream_response_uri TEXT,
  assembled_stream_uri TEXT,
  client_request_sha256 CHAR(64),
  upstream_response_sha256 CHAR(64),
  truncated BOOLEAN NOT NULL DEFAULT false,
  skipped_reason TEXT,
  store_error TEXT,
  enrich_json JSONB,
  enrich_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_exchange_user_time ON http_exchange (user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_exchange_session ON http_exchange (session_key);
CREATE INDEX IF NOT EXISTS idx_exchange_newapi_rid ON http_exchange (newapi_request_id);
CREATE INDEX IF NOT EXISTS idx_exchange_wire_time ON http_exchange (wire, created_at);
CREATE INDEX IF NOT EXISTS idx_exchange_retention ON http_exchange (retention_until)
  WHERE skipped_reason IS NULL;
