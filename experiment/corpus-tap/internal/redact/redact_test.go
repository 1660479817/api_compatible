package redact

import (
	"strings"
	"testing"
)

func TestBodyRedactsSensitiveKeys(t *testing.T) {
	in := []byte(`{"model":"gpt-4","api_key":"secret-key","nested":{"password":"p"}}`)
	out := Body(in)
	if string(out) == string(in) {
		t.Fatal("expected redaction")
	}
	if strings.Contains(string(out), "secret-key") {
		t.Fatalf("api_key leaked: %s", out)
	}
	if !strings.Contains(string(out), "[REDACTED]") {
		t.Fatalf("missing redacted marker: %s", out)
	}
}
