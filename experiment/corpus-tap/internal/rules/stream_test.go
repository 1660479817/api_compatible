package rules

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestIsStreamResponse(t *testing.T) {
	resp := &http.Response{
		Header: http.Header{"Content-Type": []string{"text/event-stream; charset=utf-8"}},
	}
	if !IsStreamResponse(resp) {
		t.Fatal("expected SSE response")
	}
}

func TestIsStreamExchangeFromResponse(t *testing.T) {
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", nil)
	resp := &http.Response{
		Header: http.Header{"Content-Type": []string{"text/event-stream"}},
	}
	if !IsStreamExchange(req, []byte(`{"stream":false}`), resp) {
		t.Fatal("expected stream from response header")
	}
}
