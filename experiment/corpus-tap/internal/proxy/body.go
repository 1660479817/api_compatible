package proxy

import (
	"bytes"
	"io"
	"net/http"
)

// requestBodyResult holds a captured body and/or a reader to forward upstream intact.
type requestBodyResult struct {
	Body         []byte
	Truncated    bool
	OversizeSkip bool
	Forward      io.ReadCloser // when set, use instead of Body for upstream (skip path)
}

// consumeRequestBody reads the client body for capture while preserving forward on oversize+skip.
func consumeRequestBody(r *http.Request, max int64, onOversize string) (requestBodyResult, error) {
	if onOversize == "skip" && r.ContentLength > 0 && r.ContentLength > max {
		return requestBodyResult{OversizeSkip: true, Forward: r.Body}, nil
	}

	// Chunked / unknown length: probe up to max+1 without losing tail on skip.
	if onOversize == "skip" && (r.ContentLength < 0 || r.ContentLength == 0) {
		return probeBodySkip(r.Body, max)
	}

	body, truncated, err := readBodyAll(r.Body, max, onOversize)
	if err != nil {
		return requestBodyResult{}, err
	}
	if onOversize == "skip" && truncated && len(body) == 0 {
		return requestBodyResult{OversizeSkip: true}, nil
	}
	return requestBodyResult{Body: body, Truncated: truncated}, nil
}

func probeBodySkip(body io.ReadCloser, max int64) (requestBodyResult, error) {
	probe := io.LimitReader(body, max+1)
	buf, err := io.ReadAll(probe)
	if err != nil {
		_ = body.Close()
		return requestBodyResult{}, err
	}
	if int64(len(buf)) <= max {
		return requestBodyResult{Body: buf, Truncated: false}, nil
	}
	// Oversize: reattach prefix + remainder for upstream forward.
	combined := io.NopCloser(io.MultiReader(bytes.NewReader(buf), body))
	return requestBodyResult{OversizeSkip: true, Forward: combined}, nil
}

func readBodyAll(rc io.ReadCloser, max int64, onOversize string) ([]byte, bool, error) {
	defer rc.Close()
	var buf bytes.Buffer
	n, err := io.Copy(&buf, io.LimitReader(rc, max+1))
	if err != nil {
		return nil, false, err
	}
	if n > max {
		if onOversize == "skip" {
			return nil, true, nil
		}
		return buf.Bytes()[:max], true, nil
	}
	return buf.Bytes(), false, nil
}

func upstreamBodyReader(body []byte, forward io.ReadCloser) io.ReadCloser {
	if forward != nil {
		return forward
	}
	if len(body) == 0 {
		return http.NoBody
	}
	return io.NopCloser(bytes.NewReader(body))
}
