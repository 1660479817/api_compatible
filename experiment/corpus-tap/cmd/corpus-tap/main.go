package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"corpus-tap/internal/capture"
	"corpus-tap/internal/config"
	"corpus-tap/internal/enrich"
	"corpus-tap/internal/proxy"
	"corpus-tap/internal/store"

	"github.com/google/uuid"
)

func main() {
	cfg := config.Load()
	if err := cfg.Valid(); err != nil {
		log.Fatal(err)
	}

	ctx := context.Background()
	var pg *store.Postgres
	var deploymentID uuid.UUID

	if cfg.DatabaseURL != "" {
		var err error
		pg, err = store.NewPostgres(ctx, cfg.DatabaseURL)
		if err != nil {
			log.Fatalf("postgres: %v", err)
		}
		defer pg.Close()
		var fixedID *uuid.UUID
		if cfg.DeploymentID != "" {
			id, err := uuid.Parse(cfg.DeploymentID)
			if err != nil {
				log.Fatalf("invalid CORPUS_TAP_DEPLOYMENT_ID: %v", err)
			}
			fixedID = &id
			deploymentID = id
		}
		deploymentID, err = pg.ResolveDeployment(ctx, fixedID, cfg.NewAPIImage, cfg.TapImage)
		if err != nil {
			log.Fatalf("deployment row: %v", err)
		}
		cfg.DeploymentID = deploymentID.String()
		if fixedID != nil {
			log.Printf("corpus-tap: deployment_id=%s (fixed)", deploymentID)
		} else {
			log.Printf("corpus-tap: deployment_id=%s (auto)", deploymentID)
		}
	} else {
		log.Print("corpus-tap: CORPUS_TAP_DATABASE_URL unset — metadata only via logs")
		if cfg.DeploymentID == "" {
			cfg.DeploymentID = "local-dev"
		}
	}

	blob, err := store.NewBlobBackend(cfg)
	if err != nil {
		log.Fatalf("blob backend: %v", err)
	}

	var tokenLookup enrich.TokenLookup
	if cfg.NewAPIMySQLDSN != "" {
		tokenLookup, err = enrich.NewMySQLLookup(cfg.NewAPIMySQLDSN)
		if err != nil {
			log.Fatalf("newapi mysql: %v", err)
		}
		log.Print("corpus-tap: token lookup via MySQL")
	} else if cfg.DevUserID > 0 {
		log.Print("corpus-tap: WARNING using CORPUS_TAP_DEV_USER_ID for all tokens")
	}
	resolver := enrich.NewResolver(tokenLookup, cfg.DevUserID, cfg.DenyUserIDs, cfg.DenyTokenIDs)

	recorder := capture.NewRecorder(cfg, pg, blob, deploymentID)
	queue := capture.NewQueue(recorder, cfg.StoreWorkers, cfg.StoreQueueSize)

	var backfiller *enrich.LogBackfiller
	if cfg.NewAPIMySQLDSN != "" && pg != nil {
		bf, err := enrich.NewLogBackfiller(cfg.NewAPIMySQLDSN, pg)
		if err != nil {
			log.Printf("corpus-tap: enrich backfill disabled: %v", err)
		} else {
			backfiller = bf
			if cfg.EnrichInterval > 0 {
				enrich.StartBackfillLoop(backfiller, time.Duration(cfg.EnrichInterval)*time.Second)
			}
		}
	}

	srv, err := proxy.New(cfg, queue, recorder, blob, pg, resolver, backfiller)
	if err != nil {
		log.Fatal(err)
	}

	httpSrv := &http.Server{
		Addr:              cfg.ListenAddr,
		Handler:           srv.Handler(),
		ReadHeaderTimeout: 30 * time.Second,
	}

	go func() {
		if cfg.NewAPIDigest != "" {
			log.Printf("corpus-tap: newapi_digest=%s", cfg.NewAPIDigest)
		}
		if cfg.SSESpoolDir != "" {
			log.Printf("corpus-tap: sse_spool_dir=%s mem=%d", cfg.SSESpoolDir, cfg.SSESpoolMemBytes)
		}
		log.Printf("corpus-tap: listen %s upstream %s proxy_only=%v",
			cfg.ListenAddr, cfg.Upstream, cfg.ProxyOnly)
		if err := httpSrv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatal(err)
		}
	}()

	ch := make(chan os.Signal, 1)
	signal.Notify(ch, syscall.SIGINT, syscall.SIGTERM)
	<-ch

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	_ = httpSrv.Shutdown(shutdownCtx)
}
