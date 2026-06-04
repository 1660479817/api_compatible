.PHONY: build test test-integration docker migrate smoke

build:
	go build -o bin/corpus-tap ./cmd/corpus-tap

test:
	go test ./...

test-integration:
	go test -tags=integration ./internal/enrich/ -count=1

smoke:
	chmod +x scripts/smoke.sh
	./scripts/smoke.sh

docker:
	docker build -t corpus-tap:dev .

run: build
	./bin/corpus-tap

migrate:
	@test -n "$(CORPUS_TAP_DATABASE_URL)" || (echo "set CORPUS_TAP_DATABASE_URL" && exit 1)
	psql "$(CORPUS_TAP_DATABASE_URL)" -f migrations/001_init.sql
	psql "$(CORPUS_TAP_DATABASE_URL)" -f migrations/002_storage_extensions.sql
