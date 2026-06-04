package enrich

import "testing"

func TestNormalizeTokenKeys(t *testing.T) {
	keys := normalizeTokenKeys("sk-abc")
	if len(keys) < 2 {
		t.Fatal(keys)
	}
	if keys[0] != "sk-abc" {
		t.Fatalf("got %v", keys)
	}
}

func TestBearerToken(t *testing.T) {
	if BearerToken("Bearer  tok ") != "tok" {
		t.Fatal()
	}
}
