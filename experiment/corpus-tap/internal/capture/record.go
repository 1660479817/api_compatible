package capture

import (
	"context"
	"encoding/json"
	"log"
	"os"
	"time"

	"corpus-tap/internal/config"
	"corpus-tap/internal/redact"
	"corpus-tap/internal/rules"
	"corpus-tap/internal/store"

	"github.com/google/uuid"
)

type Recorder struct {
	cfg          config.Config
	pg           *store.Postgres
	blob         store.BlobBackend
	deploymentID uuid.UUID
}

func NewRecorder(cfg config.Config, pg *store.Postgres, blob store.BlobBackend, deploymentID uuid.UUID) *Recorder {
	return &Recorder{cfg: cfg, pg: pg, blob: blob, deploymentID: deploymentID}
}

type Record struct {
	Ctx               context.Context
	ExchangeID        uuid.UUID
	TapRequestID      string
	UserID            int
	TokenID           int
	SessionKey        string
	Endpoint          string
	Wire              string
	IsStream          bool
	StatusCode        int
	LatencyMS         int
	ModelName         string
	ClientBody         []byte
	ResponseBody       []byte
	ResponseSpoolPath  string
	RequestHeaderJSON []byte
	NewAPIRequestID   string
	UpstreamRequestID string
	Truncated         bool
	SkipReason        string
	StoreError        string
	CreatedAt         time.Time
}

func (r *Recorder) Persist(ctx context.Context, rec Record) {
	if rec.Ctx == nil {
		rec.Ctx = ctx
	}
	if rec.ExchangeID == uuid.Nil {
		rec.ExchangeID = uuid.New()
	}
	if rec.CreatedAt.IsZero() {
		rec.CreatedAt = time.Now().UTC()
	}

	deploy := r.cfg.DeploymentID
	if deploy == "" && r.deploymentID != uuid.Nil {
		deploy = r.deploymentID.String()
	}
	if deploy == "" {
		deploy = "local-dev"
	}

	retention := rec.CreatedAt.Add(time.Duration(r.cfg.RetentionDays) * 24 * time.Hour)

	if rec.SkipReason != "" {
		if rec.UserID <= 0 {
			log.Printf("corpus-tap: skip %s tap_id=%s (no user_id)", rec.SkipReason, rec.TapRequestID)
			return
		}
		r.insertMeta(rec, deploy, &retention, "", "", "", "", "", "", 0, 0, rec.SkipReason, rec.StoreError)
		return
	}

	if rec.StoreError == "queue_full" {
		r.insertMeta(rec, deploy, &retention, "", "", "", "", "", "", 0, 0, "", rec.StoreError)
		return
	}

	client := redact.Body(rec.ClientBody)
	respRaw := rec.ResponseBody
	if len(respRaw) == 0 && rec.ResponseSpoolPath != "" {
		if b, err := os.ReadFile(rec.ResponseSpoolPath); err == nil {
			respRaw = b
		}
	}
	resp := redact.Body(respRaw)
	defer func() {
		if rec.ResponseSpoolPath != "" {
			_ = os.Remove(rec.ResponseSpoolPath)
		}
	}()
	rec.ClientBody = client
	rec.ResponseBody = resp

	var reqURI, respURI, asmURI, rawURI, hdrURI string
	var reqSHA, respSHA, asmSHA string
	var storeErr = rec.StoreError
	var clientBytes, responseBytes int64

	if r.blob != nil {
		keyBase := func(role string) store.BlobKey {
			return store.BlobKey{
				DeploymentID: deploy,
				UserID:       rec.UserID,
				ExchangeID:   rec.ExchangeID.String(),
				Role:         role,
				DT:           rec.CreatedAt,
			}
		}
		if len(client) > 0 {
			if b, err := r.blob.WriteGzip(rec.Ctx, keyBase("client_request"), client); err != nil {
				storeErr = err.Error()
			} else {
				reqURI, reqSHA = b.URI, b.SHA256
				clientBytes = b.Bytes
			}
		}
		if r.cfg.StoreHeaders && len(rec.RequestHeaderJSON) > 0 {
			h := redact.Body(rec.RequestHeaderJSON)
			if b, err := r.blob.WriteGzip(rec.Ctx, keyBase("request_headers"), h); err == nil {
				hdrURI = b.URI
			}
		}
		_ = hdrURI

		if len(resp) > 0 {
			if rec.IsStream {
				if b, err := r.blob.WriteGzip(rec.Ctx, keyBase("assembled_stream"), resp); err != nil {
					if storeErr == "" {
						storeErr = err.Error()
					}
				} else {
					asmURI, asmSHA = b.URI, b.SHA256
					responseBytes = b.Bytes
				}
				if r.cfg.StoreSSERaw {
					if b, err := r.blob.WriteGzip(rec.Ctx, keyBase("upstream_sse_raw"), resp); err == nil {
						rawURI = b.URI
					}
				}
				_ = rawURI
			} else {
				if b, err := r.blob.WriteGzip(rec.Ctx, keyBase("upstream_response"), resp); err != nil {
					if storeErr == "" {
						storeErr = err.Error()
					}
				} else {
					respURI, respSHA = b.URI, b.SHA256
					responseBytes = b.Bytes
				}
			}
		}
	} else if storeErr == "" {
		storeErr = "no_blob_backend"
	}

	r.insertMeta(rec, deploy, &retention, reqURI, respURI, asmURI, reqSHA, respSHA, asmSHA, clientBytes, responseBytes, "", storeErr)
}

func (r *Recorder) insertMeta(
	rec Record,
	deploy string,
	retention *time.Time,
	reqURI, respURI, asmURI, reqSHA, respSHA, asmSHA string,
	clientBytes, responseBytes int64,
	skipped, storeErr string,
) {
	if r.pg == nil {
		if storeErr != "" || skipped != "" {
			log.Printf("corpus-tap: meta-only user=%d exchange=%s skip=%s err=%s",
				rec.UserID, rec.ExchangeID, skipped, storeErr)
		}
		return
	}
	var dep *uuid.UUID
	if r.deploymentID != uuid.Nil {
		dep = &r.deploymentID
	} else if id, err := uuid.Parse(deploy); err == nil {
		dep = &id
	}
	row := store.ExchangeRow{
		ID:                     rec.ExchangeID,
		DeploymentID:           dep,
		CreatedAt:              rec.CreatedAt,
		RetentionUntil:         retention,
		UserID:                 rec.UserID,
		TapRequestID:           rec.TapRequestID,
		NewAPIRequestID:        rec.NewAPIRequestID,
		UpstreamRequestID:      rec.UpstreamRequestID,
		SessionKey:             rec.SessionKey,
		Endpoint:               rec.Endpoint,
		Wire:                   rec.Wire,
		IsStream:               rec.IsStream,
		StatusCode:             rec.StatusCode,
		LatencyMS:              rec.LatencyMS,
		ModelName:              rec.ModelName,
		ClientBytes:            clientBytes,
		ResponseBytes:          responseBytes,
		ClientRequestURI:       reqURI,
		UpstreamResponseURI:    respURI,
		AssembledStreamURI:     asmURI,
		ClientRequestSHA256:    reqSHA,
		UpstreamResponseSHA256: respSHA,
		Truncated:              rec.Truncated,
		SkippedReason:          skipped,
		StoreError:             storeErr,
	}
	if rec.TokenID > 0 {
		row.TokenID = &rec.TokenID
	}
	ctx2, cancel := context.WithTimeout(rec.Ctx, 30*time.Second)
	defer cancel()
	if err := r.pg.InsertExchange(ctx2, row); err != nil {
		log.Printf("corpus-tap: pg insert exchange=%s: %v", rec.ExchangeID, err)
	}
}

func Wire(path string) string { return rules.WireFormat(path) }

// ExportLine is the JSONL export shape (DESIGN §11).
type ExportLine struct {
	ExchangeID     string          `json:"exchange_id"`
	UserID         int             `json:"user_id"`
	TokenID        *int            `json:"token_id,omitempty"`
	SessionKey     string          `json:"session_key,omitempty"`
	Endpoint       string          `json:"endpoint"`
	Wire           string          `json:"wire"`
	IsStream       bool            `json:"is_stream"`
	ModelName      string          `json:"model_name,omitempty"`
	CreatedAt      time.Time       `json:"created_at"`
	RetentionUntil *time.Time      `json:"retention_until,omitempty"`
	StatusCode     int             `json:"status_code,omitempty"`
	LatencyMS      int             `json:"latency_ms,omitempty"`
	Truncated      bool            `json:"truncated"`
	URIs           map[string]*string `json:"uris"`
	SHA256         map[string]string  `json:"sha256,omitempty"`
	EnrichJSON     json.RawMessage    `json:"enrich_json,omitempty"`
}

func RowToExportLine(row store.ExchangeRow) ExportLine {
	uris := map[string]*string{
		"client_request":     strPtr(row.ClientRequestURI),
		"upstream_response": strPtr(row.UpstreamResponseURI),
		"assembled_stream":  strPtr(row.AssembledStreamURI),
	}
	sha := map[string]string{}
	if row.ClientRequestSHA256 != "" {
		sha["client_request"] = row.ClientRequestSHA256
	}
	if row.UpstreamResponseSHA256 != "" {
		sha["upstream_response"] = row.UpstreamResponseSHA256
	}
	line := ExportLine{
		ExchangeID:     row.ID.String(),
		UserID:         row.UserID,
		SessionKey:     row.SessionKey,
		Endpoint:       row.Endpoint,
		Wire:           row.Wire,
		IsStream:       row.IsStream,
		ModelName:      row.ModelName,
		CreatedAt:      row.CreatedAt,
		RetentionUntil: row.RetentionUntil,
		StatusCode:     row.StatusCode,
		LatencyMS:      row.LatencyMS,
		Truncated:      row.Truncated,
		URIs:           uris,
		SHA256:         sha,
		EnrichJSON:     row.EnrichJSON,
	}
	if row.TokenID != nil {
		line.TokenID = row.TokenID
	}
	return line
}

func strPtr(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}
