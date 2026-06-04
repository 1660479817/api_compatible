#!/usr/bin/env bash
# Recreate the application database and apply migrations/schema.sql.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${CORPUS_TAP_DATABASE_URL:-}" ]]; then
  echo "set CORPUS_TAP_DATABASE_URL" >&2
  exit 1
fi

eval "$(python3 - <<'PY'
import os
from urllib.parse import urlparse, urlunparse

app = os.environ["CORPUS_TAP_DATABASE_URL"]
u = urlparse(app)
db = (u.path or "/").lstrip("/").split("/")[0] or "postgres"
user = u.username or "postgres"
admin = os.environ.get("CORPUS_TAP_DATABASE_ADMIN_URL") or urlunparse(
    u._replace(path="/postgres")
)
# shell-safe single-quoted values
def q(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"

print(f"DB_NAME={q(db)}")
print(f"DB_USER={q(user)}")
print(f"ADMIN_URL={q(admin)}")
PY
)"

drop_and_create_db() {
  echo "==> drop and recreate database: $DB_NAME"
  psql "$ADMIN_URL" -v ON_ERROR_STOP=1 <<SQL
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS "$DB_NAME";
CREATE DATABASE "$DB_NAME" OWNER "$DB_USER";
SQL
}

reset_public_schema() {
  echo "==> reset public schema in $DB_NAME"
  psql "$CORPUS_TAP_DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL'
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO public;
SQL
}

if [[ -n "${CORPUS_TAP_DATABASE_ADMIN_URL:-}" ]]; then
  drop_and_create_db
elif drop_and_create_db 2>/dev/null; then
  true
elif reset_public_schema; then
  true
else
  echo "reset failed: grant CREATEDB to $DB_USER, or set CORPUS_TAP_DATABASE_ADMIN_URL (superuser, database postgres)" >&2
  echo "  example: export CORPUS_TAP_DATABASE_ADMIN_URL=postgres://\$(whoami)@127.0.0.1:5432/postgres" >&2
  exit 1
fi

echo "==> apply migrations/schema.sql"
psql "$CORPUS_TAP_DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/schema.sql

echo "database reset complete."
