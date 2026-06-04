-- Corpus Tap + Analysis (profile strategy) — full schema for empty PostgreSQL
-- See experiment/corpus-tap/DESIGN.md and analysis/ARCHITECTURE.md

-- L0: Tap fact layer
CREATE TABLE tap_deployment (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  newapi_image TEXT NOT NULL DEFAULT '',
  tap_image TEXT NOT NULL DEFAULT 'corpus-tap',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE http_exchange (
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

CREATE INDEX idx_exchange_user_time ON http_exchange (user_id, created_at);
CREATE INDEX idx_exchange_session ON http_exchange (session_key);
CREATE INDEX idx_exchange_newapi_rid ON http_exchange (newapi_request_id);
CREATE INDEX idx_exchange_wire_time ON http_exchange (wire, created_at);
CREATE INDEX idx_exchange_retention ON http_exchange (retention_until)
  WHERE skipped_reason IS NULL;

-- L1: Analysis platform
CREATE TABLE analysis_strategy (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  storage_model TEXT NOT NULL DEFAULT 'dedicated_tables'
    CHECK (storage_model IN ('dedicated_tables', 'unified_conclusions')),
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO analysis_strategy (id, display_name, storage_model)
VALUES ('profile', 'Gold library: exchange quality + user cohort', 'dedicated_tables');

CREATE TABLE analysis_fact_cursor (
  id TEXT PRIMARY KEY DEFAULT 'global',
  last_exchange_created_at TIMESTAMPTZ,
  last_exchange_id UUID,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO analysis_fact_cursor (id) VALUES ('global');

-- L1: Profile strategy (dedicated tables)
CREATE TABLE profile_run (
  id UUID PRIMARY KEY,
  strategy_id TEXT NOT NULL DEFAULT 'profile',
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  trigger TEXT NOT NULL DEFAULT 'cron',
  prompt_bundle_version TEXT NOT NULL,
  stats_json JSONB,
  error TEXT
);

CREATE TABLE exchange_quality (
  exchange_id UUID PRIMARY KEY REFERENCES http_exchange(id) ON DELETE CASCADE,
  user_id INT NOT NULL,
  gate_passed BOOLEAN NOT NULL DEFAULT FALSE,
  gate_reason TEXT,
  tier TEXT NOT NULL DEFAULT 'C' CHECK (tier IN ('A', 'B', 'C')),
  quality_score REAL,
  rag_indexable BOOLEAN,
  trainable_as_sft BOOLEAN,
  llm1_json JSONB,
  prompt_version TEXT,
  model_id TEXT,
  llm_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (llm_status IN ('pending', 'ok', 'failed', 'skipped_gate')),
  profile_run_id UUID REFERENCES profile_run(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_exchange_quality_user_tier ON exchange_quality (user_id, tier, updated_at DESC);
CREATE INDEX idx_exchange_quality_run ON exchange_quality (profile_run_id);

CREATE TABLE user_profile (
  user_id INT PRIMARY KEY,
  cohort TEXT NOT NULL DEFAULT 'raw' CHECK (cohort IN ('gold', 'silver', 'raw')),
  user_quality_score REAL,
  cohort_reason TEXT,
  profile_json JSONB,
  rolling_summary TEXT,
  profile_run_id UUID REFERENCES profile_run(id),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_user_profile_cohort ON user_profile (cohort);

CREATE TABLE theme_cluster (
  id UUID PRIMARY KEY,
  user_id INT NOT NULL,
  title TEXT NOT NULL,
  continuity_summary TEXT,
  exchange_ids JSONB NOT NULL DEFAULT '[]',
  time_min TIMESTAMPTZ,
  time_max TIMESTAMPTZ,
  llm4_json JSONB,
  prompt_version TEXT,
  model_id TEXT,
  profile_run_id UUID REFERENCES profile_run(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_theme_cluster_user ON theme_cluster (user_id, time_max DESC);

CREATE TABLE curated_chunk (
  id UUID PRIMARY KEY,
  exchange_id UUID NOT NULL UNIQUE REFERENCES http_exchange(id) ON DELETE CASCADE,
  user_id INT NOT NULL,
  theme_cluster_id UUID REFERENCES theme_cluster(id),
  chunk_text TEXT NOT NULL,
  title TEXT,
  metadata_json JSONB,
  chunk_uri TEXT,
  prompt_version TEXT,
  model_id TEXT,
  profile_run_id UUID REFERENCES profile_run(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_curated_chunk_user ON curated_chunk (user_id, created_at DESC);

CREATE TABLE sft_candidate (
  id UUID PRIMARY KEY,
  exchange_id UUID NOT NULL UNIQUE REFERENCES http_exchange(id) ON DELETE CASCADE,
  user_id INT NOT NULL,
  pair_json JSONB NOT NULL,
  sft_eligible BOOLEAN NOT NULL DEFAULT FALSE,
  finetune_readiness_json JSONB,
  prompt_version TEXT,
  model_id TEXT,
  profile_run_id UUID REFERENCES profile_run(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sft_candidate_user_eligible ON sft_candidate (user_id, sft_eligible)
  WHERE sft_eligible = TRUE;

-- L2: Gold library export views
CREATE VIEW v_gold_rag_chunks AS
SELECT
  c.id AS chunk_id,
  c.exchange_id,
  c.user_id,
  c.theme_cluster_id,
  c.chunk_text AS text,
  COALESCE(c.title, '') AS title,
  c.metadata_json AS metadata,
  c.created_at,
  h.session_key,
  h.wire,
  h.model_name,
  eq.quality_score,
  up.cohort
FROM curated_chunk c
JOIN http_exchange h ON h.id = c.exchange_id
JOIN exchange_quality eq ON eq.exchange_id = c.exchange_id
JOIN user_profile up ON up.user_id = c.user_id
WHERE up.cohort = 'gold'
  AND eq.tier = 'A'
  AND eq.rag_indexable = TRUE
  AND eq.llm_status = 'ok'
  AND eq.gate_passed = TRUE;

CREATE VIEW v_gold_sft_candidates AS
SELECT
  s.id,
  s.exchange_id,
  s.user_id,
  s.pair_json AS pair,
  s.created_at,
  h.session_key,
  h.wire,
  up.cohort
FROM sft_candidate s
JOIN http_exchange h ON h.id = s.exchange_id
JOIN exchange_quality eq ON eq.exchange_id = s.exchange_id
JOIN user_profile up ON up.user_id = s.user_id
WHERE up.cohort = 'gold'
  AND eq.tier = 'A'
  AND eq.llm_status = 'ok'
  AND eq.gate_passed = TRUE
  AND s.sft_eligible = TRUE
  AND eq.trainable_as_sft = TRUE;

COMMENT ON TABLE exchange_quality IS 'Profile strategy (strategy_id=profile)';
COMMENT ON VIEW v_gold_rag_chunks IS 'L2: gold + tier A + rag_indexable';
COMMENT ON VIEW v_gold_sft_candidates IS 'L2: gold + tier A + sft eligible';
