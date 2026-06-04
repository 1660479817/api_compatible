package worker

import (
	"context"
	"encoding/json"
	"log"
	"sync"
	"time"

	"corpus-tap/internal/analysis/profile/canonical"
	"corpus-tap/internal/analysis/profile/llm"
	"corpus-tap/internal/analysis/shared"
	"corpus-tap/internal/config"
	"corpus-tap/internal/store"

	"github.com/google/uuid"
)

type Worker struct {
	cfg    config.ProfileConfig
	pg     *store.Postgres
	blob   store.BlobBackend
	parser *canonical.Parser
	llm    *llm.Client
	runID  uuid.UUID
}

func New(cfg config.ProfileConfig, pg *store.Postgres, blob store.BlobBackend) *Worker {
	return &Worker{
		cfg:    cfg,
		pg:     pg,
		blob:   blob,
		parser: canonical.NewParser(blob),
		llm:    llm.NewClient(cfg.LLMBase, cfg.LLMAPIKey),
	}
}

func (w *Worker) RunOnce(ctx context.Context, trigger string) error {
	runID, err := w.pg.StartProfileRun(ctx, "profile", trigger, w.cfg.PromptVersion)
	if err != nil {
		return err
	}
	w.runID = runID
	log.Printf("analysis/profile: starting run %s (trigger=%s)", runID, trigger)

	start := time.Now()
	stats := struct {
		Processed int `json:"processed"`
		Gated     int `json:"gated"`
		LLMOK     int `json:"llm_ok"`
		Failed    int `json:"failed"`
	}{}

	rows, err := w.pg.ListPendingProfile(ctx, 1000)
	if err != nil {
		return err
	}

	sem := make(chan struct{}, w.cfg.Workers)
	var wg sync.WaitGroup
	var mu sync.Mutex
	for _, row := range rows {
		stats.Processed++
		gate := shared.RuleGate(w.cfg, row)
		if !gate.Passed {
			stats.Gated++
			_ = w.pg.UpsertExchangeQuality(ctx, store.ExchangeQuality{
				ExchangeID:   row.ID,
				UserID:       row.UserID,
				GatePassed:   false,
				GateReason:   gate.Reason,
				Tier:         "C",
				LLMStatus:    "skipped_gate",
				ProfileRunID: &w.runID,
			})
			continue
		}

		wg.Add(1)
		sem <- struct{}{}
		go func(r store.ExchangeRow) {
			defer wg.Done()
			defer func() { <-sem }()

			gated, err := w.processExchange(ctx, r)
			mu.Lock()
			switch {
			case err != nil:
				stats.Failed++
				log.Printf("analysis/profile: failed exchange %s: %v", r.ID, err)
			case gated:
				stats.Gated++
			default:
				stats.LLMOK++
			}
			mu.Unlock()
		}(row)
	}

	wg.Wait()

	var maxAt time.Time
	var maxID uuid.UUID
	for _, row := range rows {
		if maxAt.IsZero() || row.CreatedAt.After(maxAt) {
			maxAt = row.CreatedAt
			maxID = row.ID
		}
	}
	if !maxAt.IsZero() {
		_ = w.pg.UpdateAnalysisFactCursor(ctx, maxAt, maxID)
	}
	duration := time.Since(start)
	statsJSON, _ := json.Marshal(stats)
	log.Printf("analysis/profile: finished run %s in %v stats=%s", runID, duration, string(statsJSON))
	return w.pg.FinishProfileRun(ctx, runID, statsJSON, "")
}

func (w *Worker) processExchange(ctx context.Context, row store.ExchangeRow) (gated bool, err error) {
	turn, err := w.parser.Parse(ctx, row)
	if err != nil {
		err = w.pg.UpsertExchangeQuality(ctx, store.ExchangeQuality{
			ExchangeID:   row.ID,
			UserID:       row.UserID,
			GatePassed:   false,
			GateReason:   "canonical_failed: " + err.Error(),
			Tier:         "C",
			LLMStatus:    "skipped_gate",
			ProfileRunID: &w.runID,
		})
		return true, err
	}

	if turn.UserCharCount < w.cfg.MinUserChars {
		err = w.pg.UpsertExchangeQuality(ctx, store.ExchangeQuality{
			ExchangeID:   row.ID,
			UserID:       row.UserID,
			GatePassed:   false,
			GateReason:   "too_short",
			Tier:         "C",
			LLMStatus:    "skipped_gate",
			ProfileRunID: &w.runID,
		})
		return true, err
	}

	err = w.runStage1(ctx, turn)
	return false, err
}
