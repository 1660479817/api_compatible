package proxy

import (
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

func TestResponseCaptureSpoolToDisk(t *testing.T) {
	dir := t.TempDir()
	cap := newResponseCapture(1<<20, 32, dir)
	payload := strings.Repeat("x", 200)
	if _, err := cap.Write([]byte(payload)); err != nil {
		t.Fatal(err)
	}
	res, err := cap.finish()
	if err != nil {
		t.Fatal(err)
	}
	if res.SpoolPath == "" {
		t.Fatal("expected spool file")
	}
	data, err := os.ReadFile(res.SpoolPath)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != payload {
		t.Fatalf("len=%d", len(data))
	}
}

func TestRelayResponseSSESpool(t *testing.T) {
	dir := t.TempDir()
	body := strings.Repeat("data: {}\n\n", 5000)
	up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, body)
	}))
	defer up.Close()

	resp, err := http.Get(up.URL)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()

	rr := httptest.NewRecorder()
	res, err := relayResponse(rr, resp, 1<<20, 64, dir, true)
	if err != nil {
		t.Fatal(err)
	}
	if res.SpoolPath == "" && len(res.Data) < len(body) {
		t.Fatalf("spool=%q mem=%d", res.SpoolPath, len(res.Data))
	}
	removeCaptureSpool(res)
}
