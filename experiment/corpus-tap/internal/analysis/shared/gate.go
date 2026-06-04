package shared

import (
	"fmt"

	"corpus-tap/internal/config"
	"corpus-tap/internal/store"
)

// GateResult is the outcome of the shared rule gate (no semantic LLM scoring).
type GateResult struct {
	Passed bool
	Reason string
}

// RuleGate decides whether an exchange may enter an analysis strategy pipeline.
func RuleGate(cfg config.ProfileConfig, row store.ExchangeRow) GateResult {
	if row.SkippedReason != "" {
		return GateResult{Passed: false, Reason: "skipped_" + row.SkippedReason}
	}
	if row.StoreError != "" {
		return GateResult{Passed: false, Reason: "store_error_" + row.StoreError}
	}
	if row.ClientRequestURI == "" {
		return GateResult{Passed: false, Reason: "no_client_body"}
	}
	if row.StatusCode < 200 || row.StatusCode >= 300 {
		return GateResult{Passed: false, Reason: fmt.Sprintf("bad_status_%d", row.StatusCode)}
	}
	if row.Truncated && cfg.TruncatedPolicy == "strict" {
		return GateResult{Passed: false, Reason: "truncated"}
	}
	if cfg.IsDenied(row.UserID, row.TokenID) {
		return GateResult{Passed: false, Reason: "denied"}
	}
	if cfg.IsEvalAccount(row.UserID) {
		return GateResult{Passed: false, Reason: "eval_account"}
	}
	return GateResult{Passed: true}
}
