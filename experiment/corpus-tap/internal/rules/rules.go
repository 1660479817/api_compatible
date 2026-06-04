package rules

import (
	"net/http"
	"strings"
)

var capturePaths = map[string]struct{}{
	"/v1/chat/completions": {},
	"/v1/messages":          {},
	"/v1/responses":          {},
}

func ShouldCapture(r *http.Request) bool {
	if r.Method != http.MethodPost {
		return false
	}
	path := r.URL.Path
	if _, ok := capturePaths[path]; ok {
		return true
	}
	// Anthropic base URL may post to /v1/messages without /v1 prefix on some configs
	if path == "/messages" {
		return true
	}
	return false
}

func WireFormat(path string) string {
	switch {
	case strings.HasSuffix(path, "/chat/completions"):
		return "openai_chat"
	case strings.HasSuffix(path, "/messages"):
		return "anthropic_messages"
	case strings.HasSuffix(path, "/responses"):
		return "openai_responses"
	default:
		return "unknown"
	}
}

// IsStreamRequest is defined in stream.go.
