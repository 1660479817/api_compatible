package config

import (
	"os"
	"strings"
)

// ProfileConfig is used by analysis strategies (corpus-profile). Tap env vars are fallbacks for DB/blob.
type ProfileConfig struct {
	DatabaseURL      string
	LocalDataDir     string
	S3Bucket         string
	S3Region         string
	S3Endpoint       string
	S3AccessKey      string
	S3SecretKey      string
	S3ForcePathStyle bool

	LLMBase         string
	LLMAPIKey       string
	LLMModelL1      string
	LLMModelL2      string
	LLMModelL3      string
	PromptVersion   string
	IntervalHours   int
	MinUserChars    int
	Workers         int
	TruncatedPolicy string
	ListenAddr      string
	AdminKey        string

	DenyUserIDs   map[int]struct{}
	DenyTokenIDs  map[int]struct{}
	EvalUserIDs   map[int]struct{}
}

func LoadProfile() ProfileConfig {
	localDir := envOr("CORPUS_PROFILE_LOCAL_DATA_DIR", "")
	if localDir == "" {
		localDir = os.Getenv("CORPUS_TAP_LOCAL_DATA_DIR")
	}
	if localDir == "" && os.Getenv("CORPUS_PROFILE_S3_BUCKET") == "" && os.Getenv("CORPUS_TAP_S3_BUCKET") == "" {
		localDir = "./data"
	}

	dbURL := os.Getenv("CORPUS_PROFILE_DATABASE_URL")
	if dbURL == "" {
		dbURL = os.Getenv("CORPUS_TAP_DATABASE_URL")
	}

	denyUsers := mergeIntSets(
		parseIntSet(os.Getenv("CORPUS_TAP_DENY_USER_IDS")),
		parseIntSet(os.Getenv("CORPUS_PROFILE_DENY_USER_IDS")),
	)
	denyTokens := mergeIntSets(
		parseIntSet(os.Getenv("CORPUS_TAP_DENY_TOKEN_IDS")),
		parseIntSet(os.Getenv("CORPUS_PROFILE_DENY_TOKEN_IDS")),
	)

	return ProfileConfig{
		DatabaseURL:      dbURL,
		LocalDataDir:     localDir,
		S3Bucket:         envFirst("CORPUS_PROFILE_S3_BUCKET", "CORPUS_TAP_S3_BUCKET"),
		S3Region:         envFirst("CORPUS_PROFILE_S3_REGION", "CORPUS_TAP_S3_REGION"),
		S3Endpoint:       envFirst("CORPUS_PROFILE_S3_ENDPOINT", "CORPUS_TAP_S3_ENDPOINT"),
		S3AccessKey:      envFirst("CORPUS_PROFILE_S3_ACCESS_KEY", "CORPUS_TAP_S3_ACCESS_KEY"),
		S3SecretKey:      envFirst("CORPUS_PROFILE_S3_SECRET_KEY", "CORPUS_TAP_S3_SECRET_KEY"),
		S3ForcePathStyle: strings.EqualFold(envFirst("CORPUS_PROFILE_S3_FORCE_PATH_STYLE", "CORPUS_TAP_S3_FORCE_PATH_STYLE"), "true"),
		LLMBase:          os.Getenv("CORPUS_PROFILE_LLM_BASE"),
		LLMAPIKey:        os.Getenv("CORPUS_PROFILE_LLM_API_KEY"),
		LLMModelL1:       envOr("CORPUS_PROFILE_LLM_MODEL_L1", "gpt-4o-mini"),
		LLMModelL2:       envOr("CORPUS_PROFILE_LLM_MODEL_L2", "gpt-4o-mini"),
		LLMModelL3:       envOr("CORPUS_PROFILE_LLM_MODEL_L3", "gpt-4o"),
		PromptVersion:    envOr("CORPUS_PROFILE_PROMPT_VERSION", "v1"),
		IntervalHours:    parseIntEnv("CORPUS_PROFILE_USER_INTERVAL_HOURS", 24),
		MinUserChars:     parseIntEnv("CORPUS_PROFILE_MIN_USER_CHARS", 16),
		Workers:          parseIntEnv("CORPUS_PROFILE_WORKERS", 2),
		TruncatedPolicy:  envOr("CORPUS_PROFILE_TRUNCATED_POLICY", "allow"),
		ListenAddr:       envOr("CORPUS_PROFILE_LISTEN", ":8444"),
		AdminKey:         os.Getenv("CORPUS_PROFILE_ADMIN_KEY"),
		DenyUserIDs:      denyUsers,
		DenyTokenIDs:     denyTokens,
		EvalUserIDs:      parseIntSet(os.Getenv("CORPUS_PROFILE_EVAL_USER_IDS")),
	}
}

func (c ProfileConfig) Valid() error {
	if c.DatabaseURL == "" {
		return errMissing("CORPUS_PROFILE_DATABASE_URL or CORPUS_TAP_DATABASE_URL")
	}
	if c.LLMBase == "" {
		return errMissing("CORPUS_PROFILE_LLM_BASE")
	}
	if c.LLMAPIKey == "" {
		return errMissing("CORPUS_PROFILE_LLM_API_KEY")
	}
	return nil
}

// StoreConfig maps profile settings to the shared blob backend loader.
func (c ProfileConfig) StoreConfig() Config {
	return Config{
		DatabaseURL:      c.DatabaseURL,
		LocalDataDir:     c.LocalDataDir,
		S3Bucket:         c.S3Bucket,
		S3Region:         c.S3Region,
		S3Endpoint:       c.S3Endpoint,
		S3AccessKey:      c.S3AccessKey,
		S3SecretKey:      c.S3SecretKey,
		S3ForcePathStyle: c.S3ForcePathStyle,
	}
}

func (c ProfileConfig) IsDenied(userID int, tokenID *int) bool {
	if _, ok := c.DenyUserIDs[userID]; ok {
		return true
	}
	if tokenID != nil {
		if _, ok := c.DenyTokenIDs[*tokenID]; ok {
			return true
		}
	}
	return false
}

func (c ProfileConfig) IsEvalAccount(userID int) bool {
	_, ok := c.EvalUserIDs[userID]
	return ok
}

func envFirst(keys ...string) string {
	for _, k := range keys {
		if v := os.Getenv(k); v != "" {
			return v
		}
	}
	return ""
}

func mergeIntSets(sets ...map[int]struct{}) map[int]struct{} {
	out := make(map[int]struct{})
	for _, s := range sets {
		for k := range s {
			out[k] = struct{}{}
		}
	}
	return out
}
