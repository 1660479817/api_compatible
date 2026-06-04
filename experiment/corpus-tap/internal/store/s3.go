package store

import (
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"strings"

	"corpus-tap/internal/config"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

type s3Backend struct {
	client *s3.Client
	bucket string
}

func newS3Backend(cfg config.Config) (*s3Backend, error) {
	loadOpts := []func(*awsconfig.LoadOptions) error{
		awsconfig.WithRegion(cfg.S3RegionOrDefault()),
	}
	if cfg.S3AccessKey != "" && cfg.S3SecretKey != "" {
		loadOpts = append(loadOpts, awsconfig.WithCredentialsProvider(
			credentials.NewStaticCredentialsProvider(cfg.S3AccessKey, cfg.S3SecretKey, ""),
		))
	}
	awsCfg, err := awsconfig.LoadDefaultConfig(context.Background(), loadOpts...)
	if err != nil {
		return nil, err
	}
	client := s3.NewFromConfig(awsCfg, func(o *s3.Options) {
		if cfg.S3Endpoint != "" {
			o.BaseEndpoint = aws.String(cfg.S3Endpoint)
		}
		if cfg.S3ForcePathStyle {
			o.UsePathStyle = true
		}
	})
	return &s3Backend{client: client, bucket: cfg.S3Bucket}, nil
}

func (b *s3Backend) Ping(ctx context.Context) error {
	_, err := b.client.HeadBucket(ctx, &s3.HeadBucketInput{Bucket: aws.String(b.bucket)})
	return err
}

func (b *s3Backend) WriteGzip(ctx context.Context, key BlobKey, plaintext []byte) (BlobRef, error) {
	var buf bytes.Buffer
	zw := gzip.NewWriter(&buf)
	if _, err := zw.Write(plaintext); err != nil {
		return BlobRef{}, err
	}
	if err := zw.Close(); err != nil {
		return BlobRef{}, err
	}
	compressed := buf.Bytes()
	objectKey := objectPrefix(key) + "/" + blobFilename(key.Role)
	sum := sha256.Sum256(plaintext)
	sha := hex.EncodeToString(sum[:])
	_, err := b.client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(b.bucket),
		Key:         aws.String(objectKey),
		Body:        bytes.NewReader(compressed),
		ContentType: aws.String("application/gzip"),
		Metadata: map[string]string{
			"sha256":      sha,
			"exchange_id": key.ExchangeID,
			"user_id":     fmt.Sprintf("%d", key.UserID),
			"role":        key.Role,
		},
	})
	if err != nil {
		return BlobRef{}, err
	}
	uri := fmt.Sprintf("s3://%s/%s", b.bucket, objectKey)
	return BlobRef{URI: uri, SHA256: sha, Bytes: int64(len(plaintext))}, nil
}

func (b *s3Backend) ReadPlaintext(ctx context.Context, uri string) ([]byte, error) {
	if !strings.HasPrefix(uri, "s3://") {
		return nil, fmt.Errorf("not an s3 uri: %s", uri)
	}
	parts := strings.SplitN(uri[5:], "/", 2)
	if len(parts) < 2 {
		return nil, fmt.Errorf("invalid s3 uri: %s", uri)
	}
	bucket, key := parts[0], parts[1]

	resp, err := b.client.GetObject(ctx, &s3.GetObjectInput{
		Bucket: aws.String(bucket),
		Key:    aws.String(key),
	})
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	gr, err := gzip.NewReader(resp.Body)
	if err != nil {
		return nil, err
	}
	defer gr.Close()

	return io.ReadAll(gr)
}
