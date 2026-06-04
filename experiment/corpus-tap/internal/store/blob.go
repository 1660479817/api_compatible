package store

import (
	"context"
	"fmt"
	"time"

	"corpus-tap/internal/config"
)

// BlobRef is a written object pointer.
type BlobRef struct {
	URI    string
	SHA256 string
	Bytes  int64
}

// BlobKey identifies one artifact under an exchange.
type BlobKey struct {
	DeploymentID string
	UserID       int
	ExchangeID   string
	Role         string
	DT           time.Time
}

// BlobBackend writes gzip objects (local file:// or s3://).
type BlobBackend interface {
	Ping(ctx context.Context) error
	WriteGzip(ctx context.Context, key BlobKey, plaintext []byte) (BlobRef, error)
}

func NewBlobBackend(cfg config.Config) (BlobBackend, error) {
	if cfg.S3Bucket != "" {
		return newS3Backend(cfg)
	}
	if cfg.LocalDataDir != "" {
		return &localBackend{baseDir: cfg.LocalDataDir}, nil
	}
	return nil, fmt.Errorf("no blob backend: set CORPUS_TAP_S3_BUCKET or CORPUS_TAP_LOCAL_DATA_DIR")
}

func blobFilename(role string) string {
	switch role {
	case "assembled_stream":
		return "assembled_stream.txt.gz"
	case "upstream_sse_raw":
		return "upstream_sse_raw.json.gz"
	case "request_headers":
		return "request_headers.json.gz"
	case "upstream_response":
		return "upstream_response.json.gz"
	default:
		return role + ".json.gz"
	}
}

func objectPrefix(key BlobKey) string {
	dt := key.DT.UTC().Format("2006-01-02")
	return fmt.Sprintf("%s/user_id=%d/dt=%s/%s", key.DeploymentID, key.UserID, dt, key.ExchangeID)
}
