package enrich

import (
	"database/sql"
	"strings"
	"sync"
	"time"

	_ "github.com/go-sql-driver/mysql"
)

// TokenLookup resolves platform bearer tokens to New API user_id / token_id.
type TokenLookup interface {
	Lookup(tokenKey string) (userID, tokenID int, ok bool)
}

type devLookup struct {
	userID int
}

func (d devLookup) Lookup(string) (int, int, bool) {
	if d.userID <= 0 {
		return 0, 0, false
	}
	return d.userID, 0, true
}

type mysqlLookup struct {
	db    *sql.DB
	cache map[string]cacheEntry
	mu    sync.RWMutex
	ttl   time.Duration
}

type cacheEntry struct {
	userID  int
	tokenID int
	ok      bool
	expires time.Time
}

func NewMySQLLookup(dsn string) (TokenLookup, error) {
	db, err := sql.Open("mysql", dsn)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(8)
	db.SetMaxIdleConns(4)
	db.SetConnMaxLifetime(5 * time.Minute)
	if err := db.Ping(); err != nil {
		_ = db.Close()
		return nil, err
	}
	return &mysqlLookup{db: db, cache: make(map[string]cacheEntry), ttl: 2 * time.Minute}, nil
}

func (m *mysqlLookup) Lookup(key string) (int, int, bool) {
	for _, candidate := range normalizeTokenKeys(key) {
		if uid, tid, ok := m.lookupOne(candidate); ok {
			return uid, tid, true
		}
	}
	return 0, 0, false
}

func (m *mysqlLookup) lookupOne(key string) (int, int, bool) {
	m.mu.RLock()
	if e, ok := m.cache[key]; ok && time.Now().Before(e.expires) {
		m.mu.RUnlock()
		return e.userID, e.tokenID, e.ok
	}
	m.mu.RUnlock()

	var id, userID int
	// New API / One API: status=1 enabled; expired_time=-1 never expires (see testdata/NEWAPI_BASELINE.md).
	err := m.db.QueryRow(
		`SELECT id, user_id FROM tokens WHERE `+"`key`"+` = ? AND status = 1
		 AND (expired_time = -1 OR expired_time > UNIX_TIMESTAMP()) LIMIT 1`,
		key,
	).Scan(&id, &userID)
	ok := err == nil && userID > 0
	m.mu.Lock()
	m.cache[key] = cacheEntry{userID: userID, tokenID: id, ok: ok, expires: time.Now().Add(m.ttl)}
	m.mu.Unlock()
	if !ok {
		return 0, 0, false
	}
	return userID, id, true
}

func normalizeTokenKeys(raw string) []string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil
	}
	keys := []string{raw}
	if strings.HasPrefix(raw, "sk-") {
		keys = append(keys, strings.TrimPrefix(raw, "sk-"))
	} else {
		keys = append(keys, "sk-"+raw)
	}
	return keys
}

func BearerToken(auth string) string {
	const p = "Bearer "
	if !strings.HasPrefix(auth, p) {
		return ""
	}
	return strings.TrimSpace(auth[len(p):])
}
