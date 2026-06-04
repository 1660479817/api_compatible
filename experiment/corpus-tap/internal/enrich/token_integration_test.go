//go:build integration

package enrich

import (
	"os"
	"testing"
)

func TestMySQLTokenLookup_integration(t *testing.T) {
	dsn := os.Getenv("CORPUS_TAP_TEST_MYSQL_DSN")
	if dsn == "" {
		dsn = "root:corpus@tcp(127.0.0.1:13306)/newapi?parseTime=true"
	}
	lookup, err := NewMySQLLookup(dsn)
	if err != nil {
		t.Skipf("mysql not available: %v", err)
	}

	uid, tid, ok := lookup.Lookup("sk-integration-active")
	if !ok || uid != 100 || tid != 1 {
		t.Fatalf("active: uid=%d tid=%d ok=%v", uid, tid, ok)
	}
	if _, _, ok := lookup.Lookup("sk-integration-disabled"); ok {
		t.Fatal("disabled token should not resolve")
	}
	if _, _, ok := lookup.Lookup("sk-integration-expired"); ok {
		t.Fatal("expired token should not resolve")
	}
}
