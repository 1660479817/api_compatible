package proxy

import (
	"context"
	"io"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"time"

	"corpus-tap/internal/capture"
	"corpus-tap/internal/config"
	"corpus-tap/internal/enrich"
	"corpus-tap/internal/redact"
	"corpus-tap/internal/rules"
	"corpus-tap/internal/store"

	"github.com/google/uuid"
)

type Server struct {
	cfg        config.Config
	upstream   *url.URL
	proxy      *httputil.ReverseProxy
	queue      *capture.Queue
	recorder   *capture.Recorder
	blob       store.BlobBackend
	pg         *store.Postgres
	backfiller enrichBackfiller
	resolver   *enrich.Resolver
	client     *http.Client
}

type enrichBackfiller interface {
	RunOnce(ctx context.Context, limit int) (int, error)
}

func New(
	cfg config.Config,
	queue *capture.Queue,
	recorder *capture.Recorder,
	blob store.BlobBackend,
	pg *store.Postgres,
	resolver *enrich.Resolver,
	backfiller enrichBackfiller,
) (*Server, error) {
	u, err := url.Parse(cfg.Upstream)
	if err != nil {
		return nil, err
	}
	rp := httputil.NewSingleHostReverseProxy(u)
	rp.FlushInterval = -1
	return &Server{
		cfg:        cfg,
		upstream:   u,
		proxy:      rp,
		queue:      queue,
		recorder:   recorder,
		blob:       blob,
		pg:         pg,
		resolver:   resolver,
		backfiller: backfiller,
		client: &http.Client{
			Timeout: 0,
			CheckRedirect: func(req *http.Request, via []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
	}, nil
}

func (s *Server) recorderPG() *store.Postgres {
	return s.pg
}

func (s *Server) Handler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/healthz":
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte("ok"))
			return
		case "/readyz":
			s.ready(w, r)
			return
		}
		if strings.HasPrefix(r.URL.Path, "/internal/") {
			s.handleInternal(w, r)
			return
		}

		if s.cfg.ProxyOnly || !rules.ShouldCapture(r) {
			s.proxy.ServeHTTP(w, r)
			return
		}
		s.handleCapture(w, r)
	})
}

func (s *Server) ready(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, strings.TrimRight(s.upstream.String(), "/")+"/api/status", nil)
	if err != nil {
		http.Error(w, "upstream config error", http.StatusServiceUnavailable)
		return
	}
	resp, err := s.client.Do(req)
	if err != nil {
		http.Error(w, "upstream unreachable", http.StatusServiceUnavailable)
		return
	}
	_ = resp.Body.Close()

	if s.pg != nil {
		if err := s.pg.Ping(ctx); err != nil {
			http.Error(w, "database unreachable", http.StatusServiceUnavailable)
			return
		}
	}
	if s.blob != nil {
		if err := s.blob.Ping(ctx); err != nil {
			http.Error(w, "blob storage unreachable", http.StatusServiceUnavailable)
			return
		}
	}
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte("ok"))
}

func (s *Server) handleCapture(w http.ResponseWriter, r *http.Request) {
	tapID := uuid.New().String()
	exchangeID := uuid.New()
	start := time.Now()
	rec := capture.Record{
		Ctx:          context.Background(),
		ExchangeID:   exchangeID,
		TapRequestID: tapID,
		Endpoint:     r.URL.Path,
		Wire:         capture.Wire(r.URL.Path),
		SessionKey:   enrich.SessionKey(r, tapID),
		CreatedAt:    time.Now().UTC(),
	}

	subject := s.resolver.Resolve(r)
	if subject.Denied {
		rec.SkipReason = "denied"
		s.forwardAndEnqueue(w, r, nil, rec, start)
		return
	}
	if !subject.OK {
		rec.SkipReason = "enrich_failed"
		s.forwardAndEnqueue(w, r, nil, rec, start)
		return
	}
	rec.UserID = subject.UserID
	rec.TokenID = subject.TokenID

	if s.cfg.StoreHeaders {
		rec.RequestHeaderJSON = redact.HeadersJSON(r.Header)
	}

	br, err := consumeRequestBody(r, s.cfg.MaxBodyBytes, s.cfg.OnOversize)
	if err != nil {
		http.Error(w, "bad request body", http.StatusBadRequest)
		return
	}
	if br.OversizeSkip {
		rec.SkipReason = "oversize"
		s.forwardAndEnqueue(w, r, br.Forward, rec, start)
		return
	}
	rec.Truncated = br.Truncated
	rec.ClientBody = br.Body
	rec.ModelName = capture.ModelFromBody(br.Body)

	upURL := s.upstream.ResolveReference(r.URL).String()
	upBody := upstreamBodyReader(br.Body, br.Forward)
	upReq, err := http.NewRequestWithContext(r.Context(), r.Method, upURL, upBody)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	copyHeaders(upReq.Header, r.Header)
	if br.Forward == nil {
		upReq.ContentLength = int64(len(br.Body))
	} else {
		upReq.ContentLength = r.ContentLength
		upReq.TransferEncoding = r.TransferEncoding
	}
	if host := r.Host; host != "" {
		upReq.Host = host
	} else {
		upReq.Host = s.upstream.Host
	}

	upResp, err := s.client.Do(upReq)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		rec.SkipReason = "upstream_error"
		s.enqueue(rec)
		return
	}
	defer upResp.Body.Close()

	rec.IsStream = rules.IsStreamExchange(r, br.Body, upResp)

	maxCap := s.cfg.MaxBodyBytes
	if rec.IsStream {
		maxCap = s.cfg.MaxStreamBytes
	}
	memCap := s.cfg.SSESpoolMemBytes
	spoolDir := s.cfg.SSESpoolDir
	if spoolDir == "" {
		memCap = maxCap
	}
	capRes, err := relayResponse(w, upResp, maxCap, memCap, spoolDir, rec.IsStream)
	if err != nil {
		return
	}
	rec.ResponseSpoolPath = capRes.SpoolPath
	if capRes.SpoolPath == "" {
		rec.ResponseBody = capRes.Data
	}
	rec.Truncated = rec.Truncated || capRes.Truncated
	rec.StatusCode = upResp.StatusCode
	rec.LatencyMS = int(time.Since(start).Milliseconds())
	rec.NewAPIRequestID, rec.UpstreamRequestID = enrich.ResponseIDs(upResp.Header)

	s.enqueue(rec)
}

func (s *Server) forwardAndEnqueue(w http.ResponseWriter, r *http.Request, body io.ReadCloser, rec capture.Record, start time.Time) {
	if body != nil {
		r.Body = body
	}
	sr := &statusRecorder{ResponseWriter: w}
	s.proxy.ServeHTTP(sr, r)
	rec.StatusCode = sr.Status()
	rec.LatencyMS = int(time.Since(start).Milliseconds())
	s.enqueue(rec)
}

func (s *Server) enqueue(rec capture.Record) {
	if s.queue != nil && s.queue.Submit(rec) {
		return
	}
	if s.recorder == nil {
		return
	}
	if rec.StoreError == "" {
		rec.StoreError = "queue_full"
	}
	bg := context.Background()
	if rec.Ctx != nil {
		bg = rec.Ctx
	}
	s.recorder.Persist(bg, rec)
}

func copyHeaders(dst, src http.Header) {
	for k, vv := range src {
		if strings.EqualFold(k, "Connection") {
			continue
		}
		for _, v := range vv {
			dst.Add(k, v)
		}
	}
}
