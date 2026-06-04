package store

import (
	"context"
	"encoding/json"
	"strconv"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

type ExchangeRow struct {
	ID                     uuid.UUID
	DeploymentID           *uuid.UUID
	CreatedAt              time.Time
	RetentionUntil         *time.Time
	UserID                 int
	TokenID                *int
	TapRequestID           string
	NewAPIRequestID        string
	UpstreamRequestID      string
	SessionKey             string
	Endpoint               string
	Wire                   string
	IsStream               bool
	StatusCode             int
	LatencyMS              int
	ModelName              string
	ClientBytes            int64
	ResponseBytes          int64
	ClientRequestURI       string
	UpstreamResponseURI    string
	AssembledStreamURI     string
	ClientRequestSHA256    string
	UpstreamResponseSHA256 string
	AssembledStreamSHA256  string
	Truncated              bool
	SkippedReason          string
	StoreError             string
	EnrichJSON             json.RawMessage
}

type PendingEnrich struct {
	ID              uuid.UUID
	NewAPIRequestID string
}

type ExportFilters struct {
	UserIDs        []int
	From           *time.Time
	To             *time.Time
	Wire           string
	IncludeSkipped bool
	Limit          int
}

type Postgres struct {
	pool *pgxpool.Pool
}

func NewPostgres(ctx context.Context, databaseURL string) (*Postgres, error) {
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		return nil, err
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, err
	}
	return &Postgres{pool: pool}, nil
}

func (p *Postgres) Close() { p.pool.Close() }

func (p *Postgres) Ping(ctx context.Context) error {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	return p.pool.Ping(ctx)
}

func (p *Postgres) EnsureDeployment(ctx context.Context, newapiImage, tapImage string) (uuid.UUID, error) {
	var id uuid.UUID
	err := p.pool.QueryRow(ctx,
		`INSERT INTO tap_deployment (newapi_image, tap_image) VALUES ($1, $2) RETURNING id`,
		newapiImage, tapImage,
	).Scan(&id)
	return id, err
}

// ResolveDeployment uses a fixed deployment UUID when set; otherwise inserts a new row.
func (p *Postgres) ResolveDeployment(ctx context.Context, fixedID *uuid.UUID, newapiImage, tapImage string) (uuid.UUID, error) {
	if fixedID == nil || *fixedID == uuid.Nil {
		return p.EnsureDeployment(ctx, newapiImage, tapImage)
	}
	_, err := p.pool.Exec(ctx, `
INSERT INTO tap_deployment (id, newapi_image, tap_image)
VALUES ($1, $2, $3)
ON CONFLICT (id) DO UPDATE SET
  newapi_image = EXCLUDED.newapi_image,
  tap_image = EXCLUDED.tap_image`,
		*fixedID, newapiImage, tapImage,
	)
	if err != nil {
		return uuid.Nil, err
	}
	return *fixedID, nil
}

func (p *Postgres) InsertExchange(ctx context.Context, row ExchangeRow) error {
	created := row.CreatedAt
	if created.IsZero() {
		created = time.Now().UTC()
	}
	_, err := p.pool.Exec(ctx, `
INSERT INTO http_exchange (
  id, deployment_id, created_at, retention_until,
  user_id, token_id, tap_request_id, newapi_request_id, upstream_request_id, session_key,
  endpoint, wire, is_stream, status_code, latency_ms, model_name,
  client_bytes, response_bytes,
  client_request_uri, upstream_response_uri, assembled_stream_uri,
  client_request_sha256, upstream_response_sha256,
  truncated, skipped_reason, store_error
) VALUES (
  $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,
  $19,$20,$21,$22,$23,$24,$25,$26
)`,
		row.ID, row.DeploymentID, created, row.RetentionUntil,
		row.UserID, row.TokenID, row.TapRequestID, nullString(row.NewAPIRequestID), nullString(row.UpstreamRequestID), nullString(row.SessionKey),
		row.Endpoint, row.Wire, row.IsStream, row.StatusCode, row.LatencyMS, nullString(row.ModelName),
		nullInt64(row.ClientBytes), nullInt64(row.ResponseBytes),
		nullString(row.ClientRequestURI), nullString(row.UpstreamResponseURI), nullString(row.AssembledStreamURI),
		nullString(row.ClientRequestSHA256), nullString(row.UpstreamResponseSHA256),
		row.Truncated, nullString(row.SkippedReason), nullString(row.StoreError),
	)
	return err
}

func (p *Postgres) UserStats(ctx context.Context, userID int) (total int, lastCreated *time.Time, storeErrors int, err error) {
	err = p.pool.QueryRow(ctx, `
SELECT COUNT(*)::int,
       MAX(created_at),
       COUNT(*) FILTER (WHERE store_error IS NOT NULL AND store_error <> '')::int
FROM http_exchange WHERE user_id = $1`, userID).Scan(&total, &lastCreated, &storeErrors)
	return
}

func (p *Postgres) ListExport(ctx context.Context, f ExportFilters) ([]ExchangeRow, error) {
	q := `
SELECT id, deployment_id, created_at, retention_until, user_id, token_id,
       tap_request_id, COALESCE(newapi_request_id,''), COALESCE(upstream_request_id,''),
       COALESCE(session_key,''), endpoint, wire, is_stream, status_code, latency_ms,
       COALESCE(model_name,''), COALESCE(client_bytes,0), COALESCE(response_bytes,0),
       COALESCE(client_request_uri,''), COALESCE(upstream_response_uri,''), COALESCE(assembled_stream_uri,''),
       COALESCE(client_request_sha256,''), COALESCE(upstream_response_sha256,''),
       truncated, COALESCE(skipped_reason,''), COALESCE(store_error,''), enrich_json
FROM http_exchange WHERE 1=1`
	args := []any{}
	n := 0
	if len(f.UserIDs) > 0 {
		n++
		q += ` AND user_id = ANY($` + strconv.Itoa(n) + `)`
		args = append(args, f.UserIDs)
	}
	if f.From != nil {
		n++
		q += ` AND created_at >= $` + strconv.Itoa(n)
		args = append(args, *f.From)
	}
	if f.To != nil {
		n++
		q += ` AND created_at < $` + strconv.Itoa(n)
		args = append(args, *f.To)
	}
	if f.Wire != "" {
		n++
		q += ` AND wire = $` + strconv.Itoa(n)
		args = append(args, f.Wire)
	}
	if !f.IncludeSkipped {
		q += ` AND (skipped_reason IS NULL OR skipped_reason = '')`
	}
	q += ` ORDER BY created_at ASC`
	if f.Limit > 0 {
		n++
		q += ` LIMIT $` + strconv.Itoa(n)
		args = append(args, f.Limit)
	}
	rows, err := p.pool.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []ExchangeRow
	for rows.Next() {
		var r ExchangeRow
		var dep *uuid.UUID
		var tokenID *int
		var retention *time.Time
		if err := rows.Scan(
			&r.ID, &dep, &r.CreatedAt, &retention, &r.UserID, &tokenID,
			&r.TapRequestID, &r.NewAPIRequestID, &r.UpstreamRequestID, &r.SessionKey,
			&r.Endpoint, &r.Wire, &r.IsStream, &r.StatusCode, &r.LatencyMS, &r.ModelName,
			&r.ClientBytes, &r.ResponseBytes,
			&r.ClientRequestURI, &r.UpstreamResponseURI, &r.AssembledStreamURI,
			&r.ClientRequestSHA256, &r.UpstreamResponseSHA256,
			&r.Truncated, &r.SkippedReason, &r.StoreError, &r.EnrichJSON,
		); err != nil {
			return nil, err
		}
		r.DeploymentID = dep
		r.RetentionUntil = retention
		r.TokenID = tokenID
		out = append(out, r)
	}
	return out, rows.Err()
}

func (p *Postgres) ListPendingEnrich(ctx context.Context, limit int) ([]PendingEnrich, error) {
	if limit <= 0 {
		limit = 100
	}
	rows, err := p.pool.Query(ctx, `
SELECT id, COALESCE(newapi_request_id,'')
FROM http_exchange
WHERE (enrich_json IS NULL)
  AND newapi_request_id IS NOT NULL AND newapi_request_id <> ''
  AND (skipped_reason IS NULL OR skipped_reason = '')
ORDER BY created_at DESC
LIMIT $1`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []PendingEnrich
	for rows.Next() {
		var pe PendingEnrich
		if err := rows.Scan(&pe.ID, &pe.NewAPIRequestID); err != nil {
			return nil, err
		}
		out = append(out, pe)
	}
	return out, rows.Err()
}

func (p *Postgres) UpdateEnrichJSON(ctx context.Context, id uuid.UUID, payload json.RawMessage) error {
	_, err := p.pool.Exec(ctx, `
UPDATE http_exchange SET enrich_json = $2, enrich_at = now() WHERE id = $1`, id, payload)
	return err
}

func nullString(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

func nullInt64(n int64) *int64 {
	if n == 0 {
		return nil
	}
	return &n
}
