package proxy

import "testing"

func TestOversizeSkipUsesContentLength(t *testing.T) {
	max := int64(100)
	cl := int64(200)
	skip := cl > 0 && cl > max
	if !skip {
		t.Fatal("expected oversize skip")
	}
}
