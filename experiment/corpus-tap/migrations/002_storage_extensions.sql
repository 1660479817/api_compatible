-- Corpus Tap storage extensions (see experiment/corpus-tap/DESIGN.md §10)
-- Apply after 001_init.sql on existing deployments.

ALTER TABLE http_exchange
  ADD COLUMN IF NOT EXISTS retention_until TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS model_name TEXT,
  ADD COLUMN IF NOT EXISTS client_bytes BIGINT,
  ADD COLUMN IF NOT EXISTS response_bytes BIGINT,
  ADD COLUMN IF NOT EXISTS enrich_json JSONB,
  ADD COLUMN IF NOT EXISTS enrich_at TIMESTAMPTZ;

-- Backfill model_name from legacy column when present (no-op on fresh installs without model_header).
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'http_exchange' AND column_name = 'model_header'
  ) THEN
    UPDATE http_exchange
    SET model_name = model_header
    WHERE model_name IS NULL AND model_header IS NOT NULL AND model_header <> '';
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_exchange_wire_time
  ON http_exchange (wire, created_at);

CREATE INDEX IF NOT EXISTS idx_exchange_retention
  ON http_exchange (retention_until)
  WHERE skipped_reason IS NULL;
