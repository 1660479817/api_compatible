package store

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestLocalBackendWriteGzip(t *testing.T) {
	dir := t.TempDir()
	b := &localBackend{baseDir: dir}
	dt, _ := time.Parse(time.RFC3339, "2026-06-04T12:00:00Z")
	ref, err := b.WriteGzip(context.Background(), BlobKey{
		DeploymentID: "dep1",
		UserID:       7,
		ExchangeID:   "ex-1",
		Role:         "client_request",
		DT:           dt,
	}, []byte(`{"model":"m"}`))
	if err != nil {
		t.Fatal(err)
	}
	if ref.URI == "" || ref.SHA256 == "" {
		t.Fatalf("ref: %+v", ref)
	}
	path := filepath.Join(dir, "dep1", "user_id=7", "dt=2026-06-04", "ex-1", "client_request.json.gz")
	if _, err := os.Stat(path); err != nil {
		t.Fatal(err)
	}
}
