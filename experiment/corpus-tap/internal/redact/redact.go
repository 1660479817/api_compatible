package redact

import (
	"bytes"
	"encoding/json"
	"net/http"
	"strings"
)

var sensitiveKeys = map[string]struct{}{
	"api_key":       {},
	"apikey":        {},
	"secret":        {},
	"password":      {},
	"token":         {},
	"access_token":  {},
	"refresh_token": {},
	"private_key":   {},
	"client_secret": {},
}

func Headers(h http.Header) map[string][]string {
	out := make(map[string][]string, len(h))
	for k, vv := range h {
		if strings.EqualFold(k, "Authorization") {
			continue
		}
		cp := make([]string, len(vv))
		copy(cp, vv)
		out[k] = cp
	}
	return out
}

func HeadersJSON(h http.Header) []byte {
	b, _ := json.Marshal(Headers(h))
	return b
}

// Body applies R4 redaction for JSON bodies; non-JSON is returned unchanged.
func Body(b []byte) []byte {
	trim := bytes.TrimSpace(b)
	if len(trim) == 0 {
		return b
	}
	if trim[0] != '{' && trim[0] != '[' {
		return b
	}
	var v any
	if err := json.Unmarshal(trim, &v); err != nil {
		return b
	}
	redactValue(v)
	out, err := json.Marshal(v)
	if err != nil {
		return b
	}
	return out
}

func redactValue(v any) {
	switch t := v.(type) {
	case map[string]any:
		for k, val := range t {
			if _, ok := sensitiveKeys[strings.ToLower(k)]; ok {
				t[k] = "[REDACTED]"
				continue
			}
			redactValue(val)
		}
	case []any:
		for i := range t {
			redactValue(t[i])
		}
	}
}
