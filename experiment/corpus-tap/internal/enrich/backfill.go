package enrich

import (
	"context"
	"database/sql"
	"encoding/json"
	"log"
	"time"

	"corpus-tap/internal/store"

	_ "github.com/go-sql-driver/mysql"
)

// LogBackfiller fills http_exchange.enrich_json from New API MySQL logs.
type LogBackfiller struct {
	mysql *sql.DB
	pg    *store.Postgres
}

func NewLogBackfiller(mysqlDSN string, pg *store.Postgres) (*LogBackfiller, error) {
	db, err := sql.Open("mysql", mysqlDSN)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(4)
	if err := db.Ping(); err != nil {
		_ = db.Close()
		return nil, err
	}
	return &LogBackfiller{mysql: db, pg: pg}, nil
}

func (b *LogBackfiller) RunOnce(ctx context.Context, limit int) (int, error) {
	if b.pg == nil {
		return 0, nil
	}
	rows, err := b.pg.ListPendingEnrich(ctx, limit)
	if err != nil {
		return 0, err
	}
	n := 0
	for _, row := range rows {
		if row.NewAPIRequestID == "" {
			continue
		}
		payload, ok, err := b.fetchLog(ctx, row.NewAPIRequestID)
		if err != nil || !ok {
			continue
		}
		if err := b.pg.UpdateEnrichJSON(ctx, row.ID, payload); err != nil {
			log.Printf("corpus-tap: enrich update %s: %v", row.ID, err)
			continue
		}
		n++
	}
	return n, nil
}

func (b *LogBackfiller) fetchLog(ctx context.Context, requestID string) (json.RawMessage, bool, error) {
	ctx2, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	var logID, channelID, promptTokens, completionTokens int
	var quota sql.NullFloat64
	err := b.mysql.QueryRowContext(ctx2, `
SELECT id, channel_id, prompt_tokens, completion_tokens, quota
FROM logs
WHERE request_id = ?
ORDER BY id DESC
LIMIT 1`, requestID).Scan(&logID, &channelID, &promptTokens, &completionTokens, &quota)
	if err != nil {
		return nil, false, nil
	}
	m := map[string]any{
		"log_id":            logID,
		"channel_id":        channelID,
		"prompt_tokens":     promptTokens,
		"completion_tokens": completionTokens,
	}
	if quota.Valid {
		m["quota"] = quota.Float64
	}
	payload, err := json.Marshal(m)
	return payload, true, err
}

func StartBackfillLoop(b *LogBackfiller, interval time.Duration) {
	if b == nil || interval <= 0 {
		return
	}
	go func() {
		t := time.NewTicker(interval)
		defer t.Stop()
		for range t.C {
			ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
			n, err := b.RunOnce(ctx, 200)
			cancel()
			if err != nil {
				log.Printf("corpus-tap: enrich backfill: %v", err)
			} else if n > 0 {
				log.Printf("corpus-tap: enrich backfill updated %d rows", n)
			}
		}
	}()
}
