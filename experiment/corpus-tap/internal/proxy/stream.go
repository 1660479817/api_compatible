package proxy

import (
	"io"
	"net/http"
	"os"
	"path/filepath"
)

type captureResult struct {
	Data      []byte
	SpoolPath string
	Truncated bool
}

type responseCapture struct {
	mem       []byte
	memLimit  int64
	max       int64
	spoolDir  string
	spoolFile *os.File
	truncated bool
}

func newResponseCapture(max, memLimit int64, spoolDir string) *responseCapture {
	if memLimit <= 0 {
		memLimit = 1 << 20
	}
	return &responseCapture{max: max, memLimit: memLimit, spoolDir: spoolDir}
}

func (c *responseCapture) Write(p []byte) (int, error) {
	n := len(p)
	if c.truncated {
		return n, nil
	}
	remain := c.max - c.totalWritten()
	if int64(n) > remain {
		p = p[:remain]
		n = len(p)
		c.truncated = true
	}
	if n == 0 {
		return len(p), nil
	}
	if err := c.writeChunk(p); err != nil {
		return 0, err
	}
	if c.truncated && int64(n) < int64(len(p)) {
		return len(p), nil
	}
	return n, nil
}

func (c *responseCapture) totalWritten() int64 {
	if c.spoolFile != nil {
		st, err := c.spoolFile.Stat()
		if err == nil {
			return int64(len(c.mem)) + st.Size()
		}
	}
	return int64(len(c.mem))
}

func (c *responseCapture) writeChunk(p []byte) error {
	if c.spoolFile != nil {
		_, err := c.spoolFile.Write(p)
		return err
	}
	if int64(len(c.mem)+len(p)) <= c.memLimit {
		c.mem = append(c.mem, p...)
		return nil
	}
	if c.spoolDir == "" {
		room := int(c.memLimit) - len(c.mem)
		if room > 0 {
			c.mem = append(c.mem, p[:room]...)
		}
		if len(p) > room {
			c.truncated = true
		}
		return nil
	}
	if err := c.openSpool(); err != nil {
		return err
	}
	if len(c.mem) > 0 {
		if _, err := c.spoolFile.Write(c.mem); err != nil {
			return err
		}
		c.mem = nil
	}
	_, err := c.spoolFile.Write(p)
	return err
}

func (c *responseCapture) openSpool() error {
	if c.spoolFile != nil {
		return nil
	}
	if err := os.MkdirAll(c.spoolDir, 0o750); err != nil {
		return err
	}
	f, err := os.CreateTemp(c.spoolDir, "sse-spool-*.bin")
	if err != nil {
		return err
	}
	c.spoolFile = f
	return nil
}

func (c *responseCapture) finish() (captureResult, error) {
	if c.spoolFile == nil {
		return captureResult{Data: c.mem, Truncated: c.truncated}, nil
	}
	if len(c.mem) > 0 {
		if _, err := c.spoolFile.Write(c.mem); err != nil {
			_ = c.spoolFile.Close()
			_ = os.Remove(c.spoolFile.Name())
			return captureResult{}, err
		}
		c.mem = nil
	}
	path := c.spoolFile.Name()
	_ = c.spoolFile.Close()
	c.spoolFile = nil
	return captureResult{SpoolPath: path, Truncated: c.truncated}, nil
}

// relayResponse copies upstream to client while capturing up to maxCapture (with optional disk spool).
func relayResponse(w http.ResponseWriter, resp *http.Response, maxCapture, memBeforeSpool int64, spoolDir string, isStream bool) (captureResult, error) {
	copyHeaders(w.Header(), resp.Header)
	w.WriteHeader(resp.StatusCode)

	cap := newResponseCapture(maxCapture, memBeforeSpool, spoolDir)
	var written io.Writer = io.MultiWriter(w, cap)
	if f, ok := w.(http.Flusher); ok && isStream {
		written = &flushWriter{w: w, inner: io.MultiWriter(w, cap), flusher: f}
	}
	if _, err := io.Copy(written, resp.Body); err != nil {
		_ = os.Remove(cap.spoolFileName())
		return captureResult{}, err
	}
	return cap.finish()
}

func (c *responseCapture) spoolFileName() string {
	if c.spoolFile == nil {
		return ""
	}
	return c.spoolFile.Name()
}

type flushWriter struct {
	w       http.ResponseWriter
	inner   io.Writer
	flusher http.Flusher
}

func (f *flushWriter) Write(p []byte) (int, error) {
	n, err := f.inner.Write(p)
	if err == nil {
		f.flusher.Flush()
	}
	return n, err
}

// readCapturePayload loads bytes for persistence (from memory or spool file).
func readCapturePayload(res captureResult) ([]byte, error) {
	if len(res.Data) > 0 {
		return res.Data, nil
	}
	if res.SpoolPath == "" {
		return nil, nil
	}
	return os.ReadFile(filepath.Clean(res.SpoolPath))
}

// removeCaptureSpool deletes a temp spool file after persist.
func removeCaptureSpool(res captureResult) {
	if res.SpoolPath != "" {
		_ = os.Remove(res.SpoolPath)
	}
}
