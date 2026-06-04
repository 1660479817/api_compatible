package proxy

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestProbeBodySkipForwardsTail(t *testing.T) {
	const max = 8
	payload := strings.Repeat("a", 20)
	r := httptest.NewRequest(http.MethodPost, "/v1/messages", io.NopCloser(strings.NewReader(payload)))
	r.ContentLength = -1

	res, err := consumeRequestBody(r, max, "skip")
	if err != nil {
		t.Fatal(err)
	}
	if !res.OversizeSkip || res.Forward == nil {
		t.Fatalf("got %+v", res)
	}
	all, err := io.ReadAll(res.Forward)
	if err != nil {
		t.Fatal(err)
	}
	if string(all) != payload {
		t.Fatalf("forward len=%d want %d", len(all), len(payload))
	}
}

func TestProbeBodySmallFits(t *testing.T) {
	r := httptest.NewRequest(http.MethodPost, "/v1/messages", io.NopCloser(strings.NewReader(`{"x":1}`)))
	r.ContentLength = -1
	res, err := consumeRequestBody(r, 1024, "skip")
	if err != nil {
		t.Fatal(err)
	}
	if res.OversizeSkip {
		t.Fatal("unexpected skip")
	}
	if string(res.Body) != `{"x":1}` {
		t.Fatalf("body %q", res.Body)
	}
}
