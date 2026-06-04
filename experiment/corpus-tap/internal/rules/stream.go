package rules

import (
	"net/http"
	"strings"
)

// IsStreamRequest detects client-side streaming intent (Accept / JSON body).
func IsStreamRequest(r *http.Request, body []byte) bool {
	if IsEventStreamContentType(r.Header.Get("Accept")) {
		return true
	}
	lower := strings.ToLower(string(body))
	return strings.Contains(lower, `"stream":true`) || strings.Contains(lower, `"stream": true`)
}

// IsStreamResponse detects SSE from upstream response headers.
func IsStreamResponse(resp *http.Response) bool {
	if resp == nil {
		return false
	}
	if IsEventStreamContentType(resp.Header.Get("Content-Type")) {
		return true
	}
	// Some gateways leave JSON content-type but use chunked SSE on the wire.
	if strings.EqualFold(resp.Header.Get("Transfer-Encoding"), "chunked") &&
		IsEventStreamContentType(resp.Header.Get("X-Content-Type")) {
		return true
	}
	return false
}

// IsStreamExchange returns true if either request or response indicates streaming.
func IsStreamExchange(req *http.Request, reqBody []byte, resp *http.Response) bool {
	return IsStreamRequest(req, reqBody) || IsStreamResponse(resp)
}

func IsEventStreamContentType(ct string) bool {
	return strings.Contains(strings.ToLower(ct), "text/event-stream")
}
