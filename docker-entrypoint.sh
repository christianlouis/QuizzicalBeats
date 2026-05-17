#!/bin/bash
set -e

# Start the Flask application with better error reporting.
echo "Starting Flask application..."
export PYTHONUNBUFFERED=1
: "${FLASK_DEBUG:=0}"
echo "Flask environment: $FLASK_ENV"
echo "Database URI: $SQLALCHEMY_DATABASE_URI"
echo "Database path: $DATABASE_PATH"

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
