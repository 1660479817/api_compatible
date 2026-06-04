package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type ExchangeQuality struct {
	ExchangeID      uuid.UUID
	UserID          int
	GatePassed      bool
	GateReason      string
	Tier            string
	QualityScore    float32
	RagIndexable    bool
	TrainableAsSFT  bool
	LLM1JSON        json.RawMessage
	PromptVersion   string
	ModelID         string
	LLMStatus       string
	ProfileRunID    *uuid.UUID
	CreatedAt       time.Time
	UpdatedAt       time.Time
}

type ProfileRun struct {
	ID                  uuid.UUID
	StartedAt           time.Time
	FinishedAt          *time.Time
	Trigger             string
	PromptBundleVersion string
	StatsJSON           json.RawMessage
	Error               string
}

func (p *Postgres) StartProfileRun(ctx context.Context, strategyID, trigger, version string) (uuid.UUID, error) {
	if strategyID == "" {
		strategyID = "profile"
	}
	id := uuid.New()
	_, err := p.pool.Exec(ctx,
		`INSERT INTO profile_run (id, strategy_id, trigger, prompt_bundle_version) VALUES ($1, $2, $3, $4)`,
		id, strategyID, trigger, version,
	)
	return id, err
}

func (p *Postgres) FinishProfileRun(ctx context.Context, id uuid.UUID, stats json.RawMessage, errMsg string) error {
	now := time.Now()
	_, err := p.pool.Exec(ctx,
		`UPDATE profile_run SET finished_at = $2, stats_json = $3, error = $4 WHERE id = $1`,
		id, now, stats, errMsg,
	)
	return err
}

func (p *Postgres) UpsertExchangeQuality(ctx context.Context, q ExchangeQuality) error {
	_, err := p.pool.Exec(ctx, `
INSERT INTO exchange_quality (
  exchange_id, user_id, gate_passed, gate_reason, tier, quality_score,
  rag_indexable, trainable_as_sft, llm1_json, prompt_version, model_id,
  llm_status, profile_run_id
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
ON CONFLICT (exchange_id) DO UPDATE SET
  gate_passed = EXCLUDED.gate_passed,
  gate_reason = EXCLUDED.gate_reason,
  tier = EXCLUDED.tier,
  quality_score = EXCLUDED.quality_score,
  rag_indexable = EXCLUDED.rag_indexable,
  trainable_as_sft = EXCLUDED.trainable_as_sft,
  llm1_json = EXCLUDED.llm1_json,
  prompt_version = EXCLUDED.prompt_version,
  model_id = EXCLUDED.model_id,
  llm_status = EXCLUDED.llm_status,
  profile_run_id = EXCLUDED.profile_run_id,
  updated_at = NOW()`,
		q.ExchangeID, q.UserID, q.GatePassed, q.GateReason, q.Tier, q.QualityScore,
		q.RagIndexable, q.TrainableAsSFT, q.LLM1JSON, q.PromptVersion, q.ModelID,
		q.LLMStatus, q.ProfileRunID,
	)
	return err
}

func (p *Postgres) InsertCuratedChunk(ctx context.Context, exchangeID uuid.UUID, userID int, text, title string, meta json.RawMessage, runID uuid.UUID) error {
	_, err := p.pool.Exec(ctx, `
INSERT INTO curated_chunk (id, exchange_id, user_id, chunk_text, title, metadata_json, profile_run_id)
VALUES ($1, $2, $3, $4, $5, $6, $7)
ON CONFLICT (exchange_id) DO UPDATE SET
  chunk_text = EXCLUDED.chunk_text,
  title = EXCLUDED.title,
  metadata_json = EXCLUDED.metadata_json,
  profile_run_id = EXCLUDED.profile_run_id`,
		uuid.New(), exchangeID, userID, text, title, meta, runID,
	)
	return err
}

func (p *Postgres) InsertSFTCandidate(ctx context.Context, exchangeID uuid.UUID, userID int, pair json.RawMessage, eligible bool, runID uuid.UUID) error {
	_, err := p.pool.Exec(ctx, `
INSERT INTO sft_candidate (id, exchange_id, user_id, pair_json, sft_eligible, profile_run_id)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (exchange_id) DO UPDATE SET
  pair_json = EXCLUDED.pair_json,
  sft_eligible = EXCLUDED.sft_eligible,
  profile_run_id = EXCLUDED.profile_run_id`,
		uuid.New(), exchangeID, userID, pair, eligible, runID,
	)
	return err
}

func (p *Postgres) ListPendingProfile(ctx context.Context, limit int) ([]ExchangeRow, error) {
	q := `
SELECT h.id, h.deployment_id, h.created_at, h.user_id, h.token_id, COALESCE(h.session_key,''), h.endpoint, h.wire, h.is_stream,
       h.status_code, h.latency_ms, COALESCE(h.model_name,''),
       COALESCE(h.client_request_uri,''), COALESCE(h.upstream_response_uri,''), COALESCE(h.assembled_stream_uri,''),
       h.truncated, COALESCE(h.skipped_reason,''), COALESCE(h.store_error,'')
FROM http_exchange h
LEFT JOIN exchange_quality eq ON eq.exchange_id = h.id
WHERE eq.exchange_id IS NULL
  AND (h.skipped_reason IS NULL OR h.skipped_reason = '')
  AND (h.store_error IS NULL OR h.store_error = '')
  AND COALESCE(h.client_request_uri, '') <> ''
ORDER BY h.created_at ASC
LIMIT $1`
	rows, err := p.pool.Query(ctx, q, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []ExchangeRow
	for rows.Next() {
		var r ExchangeRow
		if err := rows.Scan(
			&r.ID, &r.DeploymentID, &r.CreatedAt, &r.UserID, &r.TokenID, &r.SessionKey, &r.Endpoint, &r.Wire, &r.IsStream,
			&r.StatusCode, &r.LatencyMS, &r.ModelName,
			&r.ClientRequestURI, &r.UpstreamResponseURI, &r.AssembledStreamURI,
			&r.Truncated, &r.SkippedReason, &r.StoreError,
		); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

func (p *Postgres) GetUserTierACountSinceLastProfile(ctx context.Context, userID int) (int, error) {
	var count int
	err := p.pool.QueryRow(ctx, `
SELECT COUNT(*)::int
FROM exchange_quality eq
JOIN http_exchange h ON h.id = eq.exchange_id
LEFT JOIN user_profile up ON up.user_id = eq.user_id
WHERE eq.user_id = $1 AND eq.tier = 'A' AND eq.llm_status = 'ok'
  AND (up.updated_at IS NULL OR h.created_at > up.updated_at)`, userID).Scan(&count)
	return count, err
}

func (p *Postgres) GetUserLastProfileTime(ctx context.Context, userID int) (*time.Time, error) {
	var t *time.Time
	err := p.pool.QueryRow(ctx, `SELECT updated_at FROM user_profile WHERE user_id = $1`, userID).Scan(&t)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	return t, err
}

func (p *Postgres) GetUserRecentTierA(ctx context.Context, userID int, limit int) ([]ExchangeRow, error) {
	q := `
SELECT h.id, h.created_at, h.user_id, h.session_key, h.wire, h.model_name,
       h.client_request_uri, h.upstream_response_uri, h.assembled_stream_uri
FROM http_exchange h
JOIN exchange_quality eq ON eq.exchange_id = h.id
WHERE h.user_id = $1 AND eq.tier = 'A'
ORDER BY h.created_at DESC
LIMIT $2`
	rows, err := p.pool.Query(ctx, q, userID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []ExchangeRow
	for rows.Next() {
		var r ExchangeRow
		if err := rows.Scan(
			&r.ID, &r.CreatedAt, &r.UserID, &r.SessionKey, &r.Wire, &r.ModelName,
			&r.ClientRequestURI, &r.UpstreamResponseURI, &r.AssembledStreamURI,
		); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

func (p *Postgres) UpsertUserProfile(ctx context.Context, userID int, cohort string, score float32, reason string, profile json.RawMessage, summary string, runID uuid.UUID) error {
	_, err := p.pool.Exec(ctx, `
INSERT INTO user_profile (user_id, cohort, user_quality_score, cohort_reason, profile_json, rolling_summary, profile_run_id, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
ON CONFLICT (user_id) DO UPDATE SET
  cohort = EXCLUDED.cohort,
  user_quality_score = EXCLUDED.user_quality_score,
  cohort_reason = EXCLUDED.cohort_reason,
  profile_json = EXCLUDED.profile_json,
  rolling_summary = EXCLUDED.rolling_summary,
  profile_run_id = EXCLUDED.profile_run_id,
  updated_at = NOW()`,
		userID, cohort, score, reason, profile, summary, runID,
	)
	return err
}

// GoldRAGChunkRow is the L2 export shape (view v_gold_rag_chunks).
type GoldRAGChunkRow struct {
	ChunkID      uuid.UUID       `json:"chunk_id"`
	ExchangeID   uuid.UUID       `json:"exchange_id"`
	UserID       int             `json:"user_id"`
	ThemeCluster *uuid.UUID      `json:"theme_cluster_id,omitempty"`
	Text         string          `json:"text"`
	Title        string          `json:"title"`
	Metadata     json.RawMessage `json:"metadata,omitempty"`
	CreatedAt    time.Time       `json:"created_at"`
	SessionKey   string          `json:"session_key,omitempty"`
	Wire         string          `json:"wire,omitempty"`
	ModelName    string          `json:"model_name,omitempty"`
	QualityScore *float32        `json:"quality_score,omitempty"`
	Cohort       string          `json:"cohort"`
}

func (p *Postgres) ListGoldRAGChunks(ctx context.Context, userID int, from, to *time.Time) ([]GoldRAGChunkRow, error) {
	q := `
SELECT chunk_id, exchange_id, user_id, theme_cluster_id, text, title, metadata, created_at,
       session_key, wire, model_name, quality_score, cohort
FROM v_gold_rag_chunks WHERE user_id = $1`
	args := []any{userID}
	n := 1
	if from != nil {
		n++
		q += fmt.Sprintf(" AND created_at >= $%d", n)
		args = append(args, *from)
	}
	if to != nil {
		n++
		q += fmt.Sprintf(" AND created_at < $%d", n)
		args = append(args, *to)
	}
	q += " ORDER BY created_at ASC"

	rows, err := p.pool.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []GoldRAGChunkRow
	for rows.Next() {
		var r GoldRAGChunkRow
		var theme *uuid.UUID
		var meta json.RawMessage
		var qscore *float32
		if err := rows.Scan(
			&r.ChunkID, &r.ExchangeID, &r.UserID, &theme, &r.Text, &r.Title, &meta, &r.CreatedAt,
			&r.SessionKey, &r.Wire, &r.ModelName, &qscore, &r.Cohort,
		); err != nil {
			return nil, err
		}
		r.ThemeCluster = theme
		r.Metadata = meta
		r.QualityScore = qscore
		out = append(out, r)
	}
	return out, rows.Err()
}

// GoldSFTCandidateRow is the L2 export shape (view v_gold_sft_candidates).
type GoldSFTCandidateRow struct {
	ID         uuid.UUID       `json:"id"`
	ExchangeID uuid.UUID       `json:"exchange_id"`
	UserID     int             `json:"user_id"`
	Pair       json.RawMessage `json:"pair"`
	CreatedAt  time.Time       `json:"created_at"`
	SessionKey string          `json:"session_key,omitempty"`
	Wire       string          `json:"wire,omitempty"`
	Cohort     string          `json:"cohort"`
}

func (p *Postgres) ListGoldSFTCandidates(ctx context.Context, userID int) ([]GoldSFTCandidateRow, error) {
	rows, err := p.pool.Query(ctx, `
SELECT id, exchange_id, user_id, pair, created_at, session_key, wire, cohort
FROM v_gold_sft_candidates WHERE user_id = $1 ORDER BY created_at ASC`, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []GoldSFTCandidateRow
	for rows.Next() {
		var r GoldSFTCandidateRow
		if err := rows.Scan(&r.ID, &r.ExchangeID, &r.UserID, &r.Pair, &r.CreatedAt, &r.SessionKey, &r.Wire, &r.Cohort); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

func (p *Postgres) UpdateAnalysisFactCursor(ctx context.Context, at time.Time, exchangeID uuid.UUID) error {
	_, err := p.pool.Exec(ctx, `
UPDATE analysis_fact_cursor SET
  last_exchange_created_at = GREATEST(COALESCE(last_exchange_created_at, '-infinity'::timestamptz), $1),
  last_exchange_id = $2,
  updated_at = NOW()
WHERE id = 'global'`, at, exchangeID)
	return err
}

