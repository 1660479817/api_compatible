package store

import (
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"
)

type localBackend struct {
	baseDir string
}

func (b *localBackend) Ping(ctx context.Context) error {
	select {
	case <-ctx.Done():
		return ctx.Err()
	default:
	}
	return os.MkdirAll(b.baseDir, 0o750)
}

func (b *localBackend) WriteGzip(ctx context.Context, key BlobKey, plaintext []byte) (BlobRef, error) {
	select {
	case <-ctx.Done():
		return BlobRef{}, ctx.Err()
	default:
	}
	if b.baseDir == "" {
		return BlobRef{}, fmt.Errorf("local data dir not configured")
	}
	dir := filepath.Join(b.baseDir, objectPrefix(key))
	if err := os.MkdirAll(dir, 0o750); err != nil {
		return BlobRef{}, err
	}
	path := filepath.Join(dir, blobFilename(key.Role))

	var buf bytes.Buffer
	zw := gzip.NewWriter(&buf)
	if _, err := zw.Write(plaintext); err != nil {
		return BlobRef{}, err
	}
	if err := zw.Close(); err != nil {
		return BlobRef{}, err
	}
	if err := os.WriteFile(path, buf.Bytes(), 0o640); err != nil {
		return BlobRef{}, err
	}
	sum := sha256.Sum256(plaintext)
	return BlobRef{
		URI:    "file://" + path,
		SHA256: hex.EncodeToString(sum[:]),
		Bytes:  int64(len(plaintext)),
	}, nil
}

func (b *localBackend) ReadPlaintext(ctx context.Context, uri string) ([]byte, error) {
	path := ""
	if _, err := fmt.Sscanf(uri, "file://%s", &path); err != nil {
		return nil, fmt.Errorf("invalid file uri: %w", err)
	}
	// Use Sscanf carefully with file://, it might be better to just trim prefix
	if !bytes.HasPrefix([]byte(uri), []byte("file://")) {
		return nil, fmt.Errorf("not a file uri: %s", uri)
	}
	path = uri[7:]

	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	gr, err := gzip.NewReader(f)
	if err != nil {
		return nil, err
	}
	defer gr.Close()

	return io.ReadAll(gr)
}

func localKey(deploymentID string, userID int, exchangeID, role string) BlobKey {
	return BlobKey{
		DeploymentID: deploymentID,
		UserID:       userID,
		ExchangeID:   exchangeID,
		Role:         role,
		DT:           time.Now().UTC(),
	}
}
