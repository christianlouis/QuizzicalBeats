#!/bin/bash
set -e

# Start the Flask application with better error reporting.
echo "Starting Flask application..."
export PYTHONUNBUFFERED=1
: "${FLASK_DEBUG:=0}"
echo "Flask environment: $FLASK_ENV"
mkdir -p "${ROUND_MP3_DIR:-/data/rounds}" "${ROUND_PDF_DIR:-/data/pdfs}"
python - <<'PY'
import os
import sys
from musicround.helpers.database_config import (
    bool_from_config,
    database_uri_from_postgres_env,
    database_summary,
    managed_database_requirement_error,
)

try:
    db_uri = os.environ.get("SQLALCHEMY_DATABASE_URI") or database_uri_from_postgres_env(os.environ)
except ValueError as exc:
    print(f"Database configuration error: {exc}", file=sys.stderr)
    sys.exit(78)
require_managed = bool_from_config(os.environ.get("DATABASE_REQUIRE_MANAGED"))
summary = database_summary(db_uri)
print(f"Database backend: {summary['backend']}")
print(f"Database target: {summary['redacted_uri']}")
managed_error = managed_database_requirement_error(db_uri, require_managed)
if managed_error:
    print(f"Database configuration error: {managed_error}", file=sys.stderr)
    sys.exit(78)
PY

if [ "${LOG_ENV:-0}" = "1" ]; then
  echo "Available non-sensitive environment variables:"
  env | grep -Evi '(PASSWORD|PASS|SECRET|TOKEN|KEY|AUTH|CREDENTIAL|PRIVATE)'
fi

export PYTHONFAULTHANDLER=1
export PYTHONDONTWRITEBYTECODE=1

case "${FLASK_DEBUG,,}" in
  1|true|yes|on)
    echo "Starting Flask development server with hot reload..."
    exec python -m flask run --host=0.0.0.0 --port=5000 --reload --debug
    ;;
  *)
    : "${GUNICORN_BIND:=0.0.0.0:5000}"
    : "${GUNICORN_WORKERS:=2}"
    : "${GUNICORN_THREADS:=4}"
    : "${GUNICORN_TIMEOUT:=120}"
    echo "Starting Gunicorn application server..."
    exec gunicorn \
      --bind "$GUNICORN_BIND" \
      --workers "$GUNICORN_WORKERS" \
      --threads "$GUNICORN_THREADS" \
      --timeout "$GUNICORN_TIMEOUT" \
      --access-logfile - \
      --error-logfile - \
      wsgi:app
    ;;
esac
