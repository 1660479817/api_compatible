package capture

import "testing"

func TestModelFromBody(t *testing.T) {
	body := []byte(`{"model":"claude-3","messages":[]}`)
	if got := ModelFromBody(body); got != "claude-3" {
		t.Fatalf("got %q", got)
	}
}
