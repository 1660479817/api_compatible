package proxy

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"corpus-tap/internal/capture"
	"corpus-tap/internal/config"
	"corpus-tap/internal/enrich"
	"corpus-tap/internal/store"

	"github.com/google/uuid"
)

// TestSmokeE2E runs tap against a mock New API upstream (no Docker required).
func TestSmokeE2E(t *testing.T) {
	mock := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/status":
			w.WriteHeader(http.StatusOK)
			return
		case "/v1/messages":
			if r.Header.Get("Authorization") == "" {
				http.Error(w, "no auth", http.StatusUnauthorized)
				return
			}
			w.Header().Set("Content-Type", "application/json")
			w.Header().Set("X-Request-Id", "mock-req-1")
			_ = json.NewEncoder(w).Encode(map[string]any{
				"id":   "msg_mock",
				"type": "message",
				"role": "assistant",
				"content": []map[string]string{{"type": "text", "text": "ok"}},
			})
		default:
			http.NotFound(w, r)
		}
	}))
	defer mock.Close()

	dataDir := t.TempDir()
	cfg := config.Config{
		Upstream:       mock.URL,
		LocalDataDir:   dataDir,
		DeploymentID:   "smoke-test-dep",
		DevUserID:      42,
		MaxBodyBytes:   1 << 20,
		MaxStreamBytes: 1 << 20,
		RetentionDays:  7,
		StoreWorkers:   1,
		StoreQueueSize: 8,
	}
	blob, err := store.NewBlobBackend(cfg)
	if err != nil {
		t.Fatal(err)
	}
	resolver := enrich.NewResolver(nil, cfg.DevUserID, nil, nil)
	rec := capture.NewRecorder(cfg, nil, blob, uuid.Nil)
	q := capture.NewQueue(rec, 1, 8)
	srv, err := New(cfg, q, rec, blob, nil, resolver, nil)
	if err != nil {
		t.Fatal(err)
	}

	ts := httptest.NewServer(srv.Handler())
	defer ts.Close()

	body := `{"model":"claude-test","max_tokens":16,"messages":[{"role":"user","content":"hi"}]}`
	req, _ := http.NewRequest(http.MethodPost, ts.URL+"/v1/messages", strings.NewReader(body))
	req.Header.Set("Authorization", "Bearer sk-smoke")
	req.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(resp.Body)
		t.Fatalf("status=%d body=%s", resp.StatusCode, b)
	}
	_, _ = io.Copy(io.Discard, resp.Body)

	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		matches, _ := filepath.Glob(filepath.Join(dataDir, "smoke-test-dep", "user_id=42", "dt=*", "*", "client_request.json.gz"))
		if len(matches) > 0 {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("no capture under %s", dataDir)
}

func TestForwardProxyReturnsUpstreamStatus(t *testing.T) {
	mock := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusForbidden)
		_, _ = w.Write([]byte(`{"error":"denied"}`))
	}))
	defer mock.Close()

	cfg := config.Config{Upstream: mock.URL, DevUserID: 2, MaxBodyBytes: 1024}
	resolver := enrich.NewResolver(nil, 2, nil, nil)
	rec := capture.NewRecorder(cfg, nil, nil, uuid.Nil)
	q := capture.NewQueue(rec, 1, 4)
	srv, _ := New(cfg, q, rec, nil, nil, resolver, nil)
	ts := httptest.NewServer(srv.Handler())
	defer ts.Close()

	req, _ := http.NewRequest(http.MethodPost, ts.URL+"/v1/messages", bytes.NewReader([]byte(`{"model":"m","messages":[]}`)))
	req.Header.Set("Authorization", "Bearer sk-x")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	_ = resp.Body.Close()
	if resp.StatusCode != http.StatusForbidden {
		t.Fatalf("got %d", resp.StatusCode)
	}
}
