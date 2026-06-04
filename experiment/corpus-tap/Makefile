.PHONY: build build-profile test test-integration docker db-init db-reset dev-seed dev-local smoke

build:
	go build -o bin/corpus-tap ./cmd/corpus-tap

build-profile:
	go build -o bin/corpus-profile ./cmd/corpus-profile

test:
	go test ./...

test-integration:
	go test -tags=integration ./internal/enrich/ -count=1

smoke:
	chmod +x scripts/smoke.sh scripts/reset-db.sh
	./scripts/smoke.sh

docker:
	docker build -t corpus-tap:dev .

run: build
	./bin/corpus-tap

db-init:
	@test -n "$(CORPUS_TAP_DATABASE_URL)" || (echo "set CORPUS_TAP_DATABASE_URL" && exit 1)
	psql "$(CORPUS_TAP_DATABASE_URL)" -v ON_ERROR_STOP=1 -f migrations/schema.sql

db-reset:
	@test -n "$(CORPUS_TAP_DATABASE_URL)" || (echo "set CORPUS_TAP_DATABASE_URL" && exit 1)
	chmod +x scripts/reset-db.sh
	./scripts/reset-db.sh

# Alias for docs that mentioned migrate-profile
migrate-profile: db-reset

dev-seed:
	chmod +x scripts/seed-dev-facts.sh
	./scripts/seed-dev-facts.sh

dev-local:
	chmod +x scripts/dev-local.sh scripts/seed-dev-facts.sh
	./scripts/dev-local.sh
