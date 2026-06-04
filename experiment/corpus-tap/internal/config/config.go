package config

import (
	"os"
	"strconv"
	"strings"
)

type Config struct {
	ListenAddr       string
	Upstream         string
	DatabaseURL      string
	LocalDataDir     string
	DeploymentID     string
	NewAPIImage      string
	TapImage         string
	MaxBodyBytes     int64
	OnOversize       string // truncate | skip
	MaxStreamBytes   int64
	ProxyOnly        bool
	DevUserID        int
	DenyUserIDs      map[int]struct{}
	DenyTokenIDs     map[int]struct{}
	AdminKey         string
	RetentionDays    int
	StoreWorkers     int
	StoreQueueSize   int
	StoreHeaders     bool
	StoreSSERaw      bool
	NewAPIMySQLDSN   string
	S3Bucket         string
	S3Region         string
	S3Endpoint       string
	S3AccessKey      string
	S3SecretKey      string
	S3ForcePathStyle bool
	EnrichInterval    int // seconds; 0 = disabled
	SSESpoolDir       string
	SSESpoolMemBytes  int64
	NewAPIDigest      string // locked baseline label for tests/ops (optional)
}

func Load() Config {
	maxBody := int64(32 << 20)
	if v := os.Getenv("CORPUS_TAP_MAX_BODY_BYTES"); v != "" {
		if n, err := strconv.ParseInt(v, 10, 64); err == nil && n > 0 {
			maxBody = n
		}
	}
	maxStream := int64(64 << 20)
	if v := os.Getenv("CORPUS_TAP_MAX_STREAM_BYTES"); v != "" {
		if n, err := strconv.ParseInt(v, 10, 64); err == nil && n > 0 {
			maxStream = n
		}
	}
	devUser := 0
	if v := os.Getenv("CORPUS_TAP_DEV_USER_ID"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			devUser = n
		}
	}
	retention := 90
	if v := os.Getenv("CORPUS_TAP_RETENTION_DAYS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			retention = n
		}
	}
	workers := 4
	if v := os.Getenv("CORPUS_TAP_STORE_WORKERS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			workers = n
		}
	}
	queueSize := 256
	if v := os.Getenv("CORPUS_TAP_STORE_QUEUE_SIZE"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			queueSize = n
		}
	}
	enrichInterval := 0
	if v := os.Getenv("CORPUS_TAP_ENRICH_INTERVAL_SEC"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n >= 0 {
			enrichInterval = n
		}
	}
	localDir := os.Getenv("CORPUS_TAP_LOCAL_DATA_DIR")
	if localDir == "" && os.Getenv("CORPUS_TAP_S3_BUCKET") == "" {
		localDir = "./data"
	}
	onOversize := envOr("CORPUS_TAP_ON_OVERSIZE", "truncate")
	if onOversize != "skip" {
		onOversize = "truncate"
	}
	return Config{
		ListenAddr:       envOr("CORPUS_TAP_LISTEN", ":8443"),
		Upstream:         os.Getenv("CORPUS_TAP_UPSTREAM"),
		DatabaseURL:      os.Getenv("CORPUS_TAP_DATABASE_URL"),
		LocalDataDir:     localDir,
		DeploymentID:     os.Getenv("CORPUS_TAP_DEPLOYMENT_ID"),
		NewAPIImage:      envOr("CORPUS_TAP_NEWAPI_IMAGE", "unknown"),
		TapImage:         envOr("CORPUS_TAP_IMAGE", "corpus-tap:dev"),
		MaxBodyBytes:     maxBody,
		OnOversize:       onOversize,
		MaxStreamBytes:   maxStream,
		ProxyOnly:        strings.EqualFold(os.Getenv("CORPUS_TAP_MODE"), "proxy-only"),
		DevUserID:        devUser,
		DenyUserIDs:      parseIntSet(os.Getenv("CORPUS_TAP_DENY_USER_IDS")),
		DenyTokenIDs:     parseIntSet(os.Getenv("CORPUS_TAP_DENY_TOKEN_IDS")),
		AdminKey:         os.Getenv("CORPUS_TAP_ADMIN_KEY"),
		RetentionDays:    retention,
		StoreWorkers:     workers,
		StoreQueueSize:   queueSize,
		StoreHeaders:     strings.EqualFold(os.Getenv("CORPUS_TAP_STORE_HEADERS"), "true"),
		StoreSSERaw:      strings.EqualFold(os.Getenv("CORPUS_TAP_STORE_SSE_RAW"), "true"),
		NewAPIMySQLDSN:   os.Getenv("CORPUS_TAP_NEWAPI_MYSQL_DSN"),
		S3Bucket:         os.Getenv("CORPUS_TAP_S3_BUCKET"),
		S3Region:         os.Getenv("CORPUS_TAP_S3_REGION"),
		S3Endpoint:       os.Getenv("CORPUS_TAP_S3_ENDPOINT"),
		S3AccessKey:      os.Getenv("CORPUS_TAP_S3_ACCESS_KEY"),
		S3SecretKey:      os.Getenv("CORPUS_TAP_S3_SECRET_KEY"),
		S3ForcePathStyle: strings.EqualFold(os.Getenv("CORPUS_TAP_S3_FORCE_PATH_STYLE"), "true"),
		EnrichInterval:   enrichInterval,
		SSESpoolDir:      os.Getenv("CORPUS_TAP_SSE_SPOOL_DIR"),
		SSESpoolMemBytes: parseInt64Env("CORPUS_TAP_SSE_SPOOL_MEM_BYTES", 1<<20),
		NewAPIDigest:     os.Getenv("CORPUS_TAP_NEWAPI_DIGEST"),
	}
}

func parseIntEnv(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n >= 0 {
			return n
		}
	}
	return def
}

func parseInt64Env(key string, def int64) int64 {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.ParseInt(v, 10, 64); err == nil && n > 0 {
			return n
		}
	}
	return def
}

func (c Config) Valid() error {
	if c.Upstream == "" {
		return errMissing("CORPUS_TAP_UPSTREAM")
	}
	return nil
}

func (c Config) HasBlobBackend() bool {
	return c.S3Bucket != "" || c.LocalDataDir != ""
}

func (c Config) S3RegionOrDefault() string {
	if c.S3Region != "" {
		return c.S3Region
	}
	return "us-east-1"
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func parseIntSet(s string) map[int]struct{} {
	out := make(map[int]struct{})
	for _, part := range strings.Split(s, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		if n, err := strconv.Atoi(part); err == nil {
			out[n] = struct{}{}
		}
	}
	return out
}

type missingEnv string

func (m missingEnv) Error() string { return "missing required env: " + string(m) }

func errMissing(key string) error { return missingEnv(key) }
