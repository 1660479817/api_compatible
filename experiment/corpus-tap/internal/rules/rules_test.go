package rules

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestShouldCapture(t *testing.T) {
	cases := []struct {
		method, path string
		want         bool
	}{
		{http.MethodPost, "/v1/messages", true},
		{http.MethodPost, "/v1/chat/completions", true},
		{http.MethodGet, "/v1/models", false},
		{http.MethodPost, "/v1/embeddings", false},
	}
	for _, tc := range cases {
		r := httptest.NewRequest(tc.method, tc.path, nil)
		if got := ShouldCapture(r); got != tc.want {
			t.Fatalf("%s %s: got %v want %v", tc.method, tc.path, got, tc.want)
		}
	}
}

func TestIsStreamRequest(t *testing.T) {
	r := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", nil)
	r.Header.Set("Accept", "text/event-stream")
	if !IsStreamRequest(r, []byte(`{"stream":false}`)) {
		t.Fatal("expected stream from Accept")
	}
}
