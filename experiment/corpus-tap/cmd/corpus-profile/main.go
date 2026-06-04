package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"corpus-tap/internal/analysis/profile/worker"
	"corpus-tap/internal/config"
	"corpus-tap/internal/store"
)

func main() {
	cfg := config.LoadProfile()
	if err := cfg.Valid(); err != nil {
		log.Fatal(err)
	}

	ctx := context.Background()
	pg, err := store.NewPostgres(ctx, cfg.DatabaseURL)
	if err != nil {
		log.Fatalf("postgres: %v", err)
	}
	defer pg.Close()

	blob, err := store.NewBlobBackend(cfg.StoreConfig())
	if err != nil {
		log.Fatalf("blob: %v", err)
	}

	w := worker.New(cfg, pg, blob)

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})

	mux.HandleFunc("/internal/run", func(res http.ResponseWriter, r *http.Request) {
		if !checkAdmin(r, cfg.AdminKey) {
			http.Error(res, "unauthorized", http.StatusUnauthorized)
			return
		}
		if r.Method != http.MethodPost {
			http.Error(res, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		go func() {
			if err := w.RunOnce(context.Background(), "manual"); err != nil {
				log.Printf("analysis/profile run failed: %v", err)
			}
		}()
		res.WriteHeader(http.StatusAccepted)
		_, _ = res.Write([]byte("run started in background"))
	})

	mux.HandleFunc("/profile/export/rag", func(res http.ResponseWriter, r *http.Request) {
		if !checkAdmin(r, cfg.AdminKey) {
			http.Error(res, "unauthorized", http.StatusUnauthorized)
			return
		}
		userID, ok := parseUserIDQuery(r)
		if !ok {
			http.Error(res, "missing user_id", http.StatusBadRequest)
			return
		}
		chunks, err := pg.ListGoldRAGChunks(r.Context(), userID, nil, nil)
		if err != nil {
			http.Error(res, err.Error(), http.StatusInternalServerError)
			return
		}
		writeJSONL(res, chunks)
	})

	mux.HandleFunc("/profile/export/sft", func(res http.ResponseWriter, r *http.Request) {
		if !checkAdmin(r, cfg.AdminKey) {
			http.Error(res, "unauthorized", http.StatusUnauthorized)
			return
		}
		userID, ok := parseUserIDQuery(r)
		if !ok {
			http.Error(res, "missing user_id", http.StatusBadRequest)
			return
		}
		candidates, err := pg.ListGoldSFTCandidates(r.Context(), userID)
		if err != nil {
			http.Error(res, err.Error(), http.StatusInternalServerError)
			return
		}
		writeJSONL(res, candidates)
	})

	srv := &http.Server{Addr: cfg.ListenAddr, Handler: mux}
	go func() {
		log.Printf("corpus-profile: listening on %s (strategy=profile)", cfg.ListenAddr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("listen: %v", err)
		}
	}()

	go func() {
		ticker := time.NewTicker(time.Hour)
		defer ticker.Stop()
		for range ticker.C {
			log.Printf("analysis/profile: scheduled run")
			_ = w.RunOnce(context.Background(), "cron")
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop

	log.Println("corpus-profile: shutting down")
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = srv.Shutdown(shutdownCtx)
}

func checkAdmin(r *http.Request, key string) bool {
	if key == "" {
		return true
	}
	if r.Header.Get("X-Corpus-Admin-Key") == key {
		return true
	}
	if r.Header.Get("X-Admin-Key") == key {
		return true
	}
	if auth := r.Header.Get("Authorization"); strings.HasPrefix(auth, "Bearer ") {
		return strings.TrimSpace(strings.TrimPrefix(auth, "Bearer ")) == key
	}
	return false
}

func parseUserIDQuery(r *http.Request) (int, bool) {
	userIDStr := r.URL.Query().Get("user_id")
	if userIDStr == "" {
		return 0, false
	}
	userID, err := strconv.Atoi(userIDStr)
	if err != nil || userID <= 0 {
		return 0, false
	}
	return userID, true
}

func writeJSONL(w http.ResponseWriter, rows any) {
	w.Header().Set("Content-Type", "application/x-ndjson")
	enc := json.NewEncoder(w)
	switch v := rows.(type) {
	case []store.GoldRAGChunkRow:
		for _, row := range v {
			_ = enc.Encode(row)
		}
	case []store.GoldSFTCandidateRow:
		for _, row := range v {
			_ = enc.Encode(row)
		}
	}
}
