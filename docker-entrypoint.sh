#!/bin/bash
set -e

# Run the OAuth migration script first
echo "Running database migration for OAuth providers..."
python run_migration.py

# Start the Flask application with better error reporting
echo "Starting Flask application..."
export PYTHONUNBUFFERED=1
export FLASK_DEBUG=1
echo "Flask environment: $FLASK_ENV"
echo "Database URI: $SQLALCHEMY_DATABASE_URI"
echo "Database path: $DATABASE_PATH"
echo "Available environment variables:"
env | grep -v PASSWORD | grep -v SECRET

# Use flask run with explicit reload for better hot reloading
export PYTHONFAULTHANDLER=1
export PYTHONDONTWRITEBYTECODE=1

echo "Starting Flask development server with hot reload..."
exec python -m flask run --host=0.0.0.0 --port=5000 --reload --debug || {
  echo "Flask application failed to start. Error details:"
  python -c "import traceback; traceback.print_exc()"
  exit 1
}