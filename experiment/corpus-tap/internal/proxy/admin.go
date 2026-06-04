package proxy

import (
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"time"

	"corpus-tap/internal/capture"
	"corpus-tap/internal/store"
)

func (s *Server) handleInternal(w http.ResponseWriter, r *http.Request) {
	if !s.checkAdmin(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	switch {
	case r.Method == http.MethodGet && r.URL.Path == "/internal/stats":
		s.handleStats(w, r)
	case r.Method == http.MethodGet && r.URL.Path == "/internal/export":
		s.handleExport(w, r)
	case r.Method == http.MethodPost && r.URL.Path == "/internal/reload-enrich":
		s.handleReloadEnrich(w, r)
	default:
		http.NotFound(w, r)
	}
}

func (s *Server) checkAdmin(r *http.Request) bool {
	if s.cfg.AdminKey == "" {
		return false
	}
	if r.Header.Get("X-Corpus-Admin-Key") == s.cfg.AdminKey {
		return true
	}
	if auth := r.Header.Get("Authorization"); strings.HasPrefix(auth, "Bearer ") {
		return strings.TrimSpace(strings.TrimPrefix(auth, "Bearer ")) == s.cfg.AdminKey
	}
	return false
}

func (s *Server) handleStats(w http.ResponseWriter, r *http.Request) {
	if s.recorderPG() == nil {
		http.Error(w, "database not configured", http.StatusServiceUnavailable)
		return
	}
	uid, _ := strconv.Atoi(r.URL.Query().Get("user_id"))
	if uid <= 0 {
		http.Error(w, "user_id required", http.StatusBadRequest)
		return
	}
	total, last, errs, err := s.recorderPG().UserStats(r.Context(), uid)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	out := map[string]any{
		"user_id":      uid,
		"total":        total,
		"store_errors": errs,
	}
	if last != nil {
		out["last_created_at"] = last.UTC().Format(time.RFC3339)
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(out)
}

func (s *Server) handleExport(w http.ResponseWriter, r *http.Request) {
	pg := s.recorderPG()
	if pg == nil {
		http.Error(w, "database not configured", http.StatusServiceUnavailable)
		return
	}
	ids, err := parseUserIDs(r.URL.Query().Get("user_id"))
	if err != nil || len(ids) == 0 {
		http.Error(w, "user_id required", http.StatusBadRequest)
		return
	}
	f := store.ExportFilters{UserIDs: ids, Wire: r.URL.Query().Get("wire"), IncludeSkipped: r.URL.Query().Get("include_skipped") == "true"}
	if v := r.URL.Query().Get("limit"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			f.Limit = n
		}
	}
	if v := r.URL.Query().Get("from"); v != "" {
		if t, err := time.Parse(time.RFC3339, v); err == nil {
			f.From = &t
		}
	}
	if v := r.URL.Query().Get("to"); v != "" {
		if t, err := time.Parse(time.RFC3339, v); err == nil {
			f.To = &t
		}
	}
	rows, err := pg.ListExport(r.Context(), f)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/x-ndjson")
	enc := json.NewEncoder(w)
	for _, row := range rows {
		_ = enc.Encode(capture.RowToExportLine(row))
	}
}

func (s *Server) handleReloadEnrich(w http.ResponseWriter, r *http.Request) {
	if s.backfiller == nil {
		http.Error(w, "enrich not configured", http.StatusServiceUnavailable)
		return
	}
	n, err := s.backfiller.RunOnce(r.Context(), 500)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]int{"updated": n})
}

func parseUserIDs(s string) ([]int, error) {
	var ids []int
	for _, part := range strings.Split(s, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		n, err := strconv.Atoi(part)
		if err != nil {
			return nil, err
		}
		ids = append(ids, n)
	}
	return ids, nil
}
