package enrich

import (
	"net/http"
	"strings"
)

type Subject struct {
	UserID  int
	TokenID int
	OK      bool
	Denied  bool
}

type Resolver struct {
	lookup      TokenLookup
	devUserID   int
	denyUsers   map[int]struct{}
	denyTokens  map[int]struct{}
}

func NewResolver(lookup TokenLookup, devUserID int, denyUsers, denyTokens map[int]struct{}) *Resolver {
	if lookup == nil {
		if devUserID > 0 {
			lookup = devLookup{userID: devUserID}
		}
	}
	return &Resolver{
		lookup:     lookup,
		devUserID:  devUserID,
		denyUsers:  denyUsers,
		denyTokens: denyTokens,
	}
}

func (r *Resolver) Resolve(req *http.Request) Subject {
	if r.lookup == nil {
		return Subject{}
	}
	key := BearerToken(req.Header.Get("Authorization"))
	if key == "" {
		key = strings.TrimSpace(req.Header.Get("x-api-key"))
	}
	if key == "" {
		return Subject{}
	}
	uid, tid, ok := r.lookup.Lookup(key)
	if !ok {
		return Subject{}
	}
	if _, denied := r.denyUsers[uid]; denied {
		return Subject{UserID: uid, TokenID: tid, Denied: true}
	}
	if tid > 0 {
		if _, denied := r.denyTokens[tid]; denied {
			return Subject{UserID: uid, TokenID: tid, Denied: true}
		}
	}
	return Subject{UserID: uid, TokenID: tid, OK: true}
}

func SessionKey(r *http.Request, tapRequestID string) string {
	if s := strings.TrimSpace(r.Header.Get("X-Corpus-Session-Id")); s != "" {
		return s
	}
	return tapRequestID
}

func ResponseIDs(h http.Header) (newapiRequestID, upstreamRequestID string) {
	for _, k := range []string{
		"X-Request-Id",
		"X-Request-ID",
		"X-Oneapi-Request-Id",
		"X-New-Api-Request-Id",
	} {
		if v := strings.TrimSpace(h.Get(k)); v != "" {
			newapiRequestID = v
			break
		}
	}
	for _, k := range []string{"X-Openai-Request-Id", "X-OpenAI-Request-Id"} {
		if v := strings.TrimSpace(h.Get(k)); v != "" {
			upstreamRequestID = v
			break
		}
	}
	return newapiRequestID, upstreamRequestID
}
