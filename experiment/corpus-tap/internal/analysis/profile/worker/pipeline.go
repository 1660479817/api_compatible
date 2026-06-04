package worker

import (
	"bytes"
	"context"
	"embed"
	"encoding/json"
	"fmt"
	"log"
	"text/template"
	"time"

	"corpus-tap/internal/analysis/profile/canonical"
	"corpus-tap/internal/analysis/profile/llm"
	"corpus-tap/internal/store"
)

//go:embed prompts/*
var promptFS embed.FS

func (w *Worker) runStage1(ctx context.Context, turn *canonical.CanonicalTurn) error {
	tmplPath := fmt.Sprintf("prompts/%s/stage1_quality_curation.md", w.cfg.PromptVersion)
	tmplBytes, err := promptFS.ReadFile(tmplPath)
	if err != nil {
		return fmt.Errorf("read prompt template: %w", err)
	}

	tmpl, err := template.New("stage1").Parse(string(tmplBytes))
	if err != nil {
		return fmt.Errorf("parse prompt template: %w", err)
	}

	convJSON, _ := json.MarshalIndent(turn.Messages, "", "  ")
	var promptBuf bytes.Buffer
	if err := tmpl.Execute(&promptBuf, map[string]any{
		"ConversationJSON": string(convJSON),
	}); err != nil {
		return fmt.Errorf("execute prompt template: %w", err)
	}

	resp, err := w.llm.ChatCompletion(ctx, llm.ChatRequest{
		Model: w.cfg.LLMModelL1,
		Messages: []llm.Message{
			{Role: "user", Content: promptBuf.String()},
		},
		ResponseFormat: &llm.ResponseFormat{Type: "json_object"},
	})
	if err != nil {
		return w.pg.UpsertExchangeQuality(ctx, store.ExchangeQuality{
			ExchangeID:   turn.ExchangeID,
			UserID:       turn.UserID,
			GatePassed:   true,
			LLMStatus:    "failed",
			Tier:         "C",
			ProfileRunID: &w.runID,
		})
	}

	var result struct {
		Tier         string  `json:"tier"`
		QualityScore float32 `json:"quality_score"`
		RagIndexable bool    `json:"rag_indexable"`
		CuratedChunk *struct {
			Title string `json:"title"`
			Text  string `json:"text"`
		} `json:"curated_chunk"`
		SFTCandidate *struct {
			Instruction string `json:"instruction"`
			Output      string `json:"output"`
			Eligible    bool   `json:"eligible"`
		} `json:"sft_candidate"`
		Evidence string `json:"evidence"`
	}

	if err := json.Unmarshal([]byte(resp.Choices[0].Message.Content), &result); err != nil {
		return w.pg.UpsertExchangeQuality(ctx, store.ExchangeQuality{
			ExchangeID:   turn.ExchangeID,
			UserID:       turn.UserID,
			GatePassed:   true,
			LLMStatus:    "failed", // JSON parse error
			Tier:         "C",
			ProfileRunID: &w.runID,
		})
	}

	// Persist Stage 1 result
	q := store.ExchangeQuality{
		ExchangeID:     turn.ExchangeID,
		UserID:         turn.UserID,
		GatePassed:     true,
		Tier:           normalizeTier(result.Tier),
		QualityScore:   result.QualityScore,
		RagIndexable:   result.RagIndexable,
		TrainableAsSFT: result.SFTCandidate != nil && result.SFTCandidate.Eligible,
		LLM1JSON:       json.RawMessage(resp.Choices[0].Message.Content),
		PromptVersion:  w.cfg.PromptVersion,
		ModelID:        w.cfg.LLMModelL1,
		LLMStatus:      "ok",
		ProfileRunID:   &w.runID,
	}
	if err := w.pg.UpsertExchangeQuality(ctx, q); err != nil {
		return err
	}

	// If Tier A, persist curated assets
	switch normalizeTier(result.Tier) {
	case "A":
		if result.CuratedChunk != nil {
			_ = w.pg.InsertCuratedChunk(ctx, turn.ExchangeID, turn.UserID, result.CuratedChunk.Text, result.CuratedChunk.Title, nil, w.runID)
		}
		if result.SFTCandidate != nil {
			pair, _ := json.Marshal(result.SFTCandidate)
			_ = w.pg.InsertSFTCandidate(ctx, turn.ExchangeID, turn.UserID, pair, result.SFTCandidate.Eligible, w.runID)
		}

		// Check thresholds for user profiling
		if err := w.checkAndRunUserProfiling(ctx, turn.UserID); err != nil {
			log.Printf("analysis/profile: user profiling failed for %d: %v", turn.UserID, err)
		}
	}

	return nil
}

func normalizeTier(t string) string {
	switch t {
	case "A", "B", "C":
		return t
	default:
		return "C"
	}
}

func (w *Worker) checkAndRunUserProfiling(ctx context.Context, userID int) error {
	count, err := w.pg.GetUserTierACountSinceLastProfile(ctx, userID)
	if err != nil {
		return err
	}

	lastUpdate, err := w.pg.GetUserLastProfileTime(ctx, userID)
	if err != nil {
		return err
	}

	shouldUpdate := count >= 10
	if !shouldUpdate && lastUpdate != nil {
		if time.Since(*lastUpdate) > time.Duration(w.cfg.IntervalHours)*time.Hour {
			shouldUpdate = count > 0
		}
	} else if lastUpdate == nil {
		shouldUpdate = count > 0
	}

	if !shouldUpdate {
		return nil
	}

	return w.runUserProfiling(ctx, userID)
}

func (w *Worker) runUserProfiling(ctx context.Context, userID int) error {
	recent, err := w.pg.GetUserRecentTierA(ctx, userID, 50)
	if err != nil {
		return err
	}

	var interactionTexts []string
	for _, r := range recent {
		t, err := w.parser.Parse(ctx, r)
		if err == nil {
			// Just use a simplified version for the profiling prompt
			interactionTexts = append(interactionTexts, fmt.Sprintf("ID: %s\nWire: %s\nModel: %s\nMessages: %v", r.ID, r.Wire, r.ModelName, t.Messages))
		}
	}

	tmplPath := fmt.Sprintf("prompts/%s/stage2_user_profiling.md", w.cfg.PromptVersion)
	tmplBytes, err := promptFS.ReadFile(tmplPath)
	if err != nil {
		return err
	}
	tmpl, _ := template.New("stage2").Parse(string(tmplBytes))

	interactionsJSON, _ := json.Marshal(interactionTexts)
	var promptBuf bytes.Buffer
	tmpl.Execute(&promptBuf, map[string]any{
		"InteractionsJSON": string(interactionsJSON),
	})

	resp, err := w.llm.ChatCompletion(ctx, llm.ChatRequest{
		Model: w.cfg.LLMModelL2,
		Messages: []llm.Message{
			{Role: "user", Content: promptBuf.String()},
		},
		ResponseFormat: &llm.ResponseFormat{Type: "json_object"},
	})
	if err != nil {
		return err
	}

	var result struct {
		Cohort           string          `json:"cohort"`
		UserQualityScore float32         `json:"user_quality_score"`
		CohortReason     string          `json:"cohort_reason"`
		ProfileJSON      json.RawMessage `json:"profile_json"`
		RollingSummary   string          `json:"rolling_summary"`
	}

	if err := json.Unmarshal([]byte(resp.Choices[0].Message.Content), &result); err != nil {
		return err
	}

	return w.pg.UpsertUserProfile(ctx, userID, result.Cohort, result.UserQualityScore, result.CohortReason, result.ProfileJSON, result.RollingSummary, w.runID)
}
