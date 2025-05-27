import sys
import os
import contextlib
from sqlalchemy import text

# Add project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from musicround import db, create_app
from musicround.models import User  # Import your User model

# Migration name (used for logging and tracking)
migration_name = os.path.splitext(os.path.basename(__file__))[0]

def run_migration():
    # Check if an app context already exists (e.g., if called from within Flask app)
    from flask import current_app
    try:
        app = current_app._get_current_object()
        app_context_needed = False
    except Exception:
        app = create_app()
        app_context_needed = True

    context_manager = app.app_context() if app_context_needed else contextlib.nullcontext()
    with context_manager:
        try:
            print(f"Starting migration: {migration_name}")

            # Use raw SQL for schema changes to avoid issues with model definitions
            # that might already expect the columns to exist.

            # Check if spotify_id column exists
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('user')]

            if 'oauth_id' in columns and 'spotify_id' not in columns:
                # Option 1: Rename oauth_id to spotify_id if oauth_id was intended for Spotify
                # This is less safe if oauth_id was used for something else or if data types differ.
                # print("Attempting to rename column 'oauth_id' to 'spotify_id'.")
                # with db.engine.connect() as connection:
                #     connection.execute(text('ALTER TABLE user RENAME COLUMN oauth_id TO spotify_id'))
                #     connection.commit()
                # print("Renamed 'oauth_id' to 'spotify_id'.")
                #
                # Or, if oauth_id is definitely old and spotify_id is new:
                print("Column 'oauth_id' exists. It will be kept for now. Adding 'spotify_id'.")

            if 'spotify_id' not in columns:
                print("Adding column 'spotify_id' to 'user' table.")
                with db.engine.connect() as connection:
                    connection.execute(text('ALTER TABLE user ADD COLUMN spotify_id VARCHAR(100)'))
                    connection.commit()
                print("Added 'spotify_id'.")
            else:
                print("Column 'spotify_id' already exists.")

            if 'spotify_token' not in columns:
                print("Adding column 'spotify_token' to 'user' table.")
                with db.engine.connect() as connection:
                    connection.execute(text('ALTER TABLE user ADD COLUMN spotify_token TEXT'))
                    connection.commit()
                print("Added 'spotify_token'.")
            else:
                print("Column 'spotify_token' already exists.")

            if 'spotify_refresh_token' not in columns:
                print("Adding column 'spotify_refresh_token' to 'user' table.")
                with db.engine.connect() as connection:
                    connection.execute(text('ALTER TABLE user ADD COLUMN spotify_refresh_token TEXT'))
                    connection.commit()
                print("Added 'spotify_refresh_token'.")
            else:
                print("Column 'spotify_refresh_token' already exists.")

            if 'spotify_token_expiry' not in columns:
                print("Adding column 'spotify_token_expiry' to 'user' table.")
                with db.engine.connect() as connection:
                    connection.execute(text('ALTER TABLE user ADD COLUMN spotify_token_expiry DATETIME'))
                    connection.commit()
                print("Added 'spotify_token_expiry'.")
            else:
                print("Column 'spotify_token_expiry' already exists.")
            
            # Add index to spotify_id if it doesn't exist
            # Index creation syntax can vary between DBs (e.g., SQLite vs PostgreSQL)
            # For SQLite, it's generally: CREATE INDEX IF NOT EXISTS idx_user_spotify_id ON user (spotify_id);
            # For SQLAlchemy, it's better to define this in the model and let Alembic/Flask-Migrate handle it,
            # but for a manual script:
            try:
                with db.engine.connect() as connection:
                    # Check if index exists first (SQLite specific query)
                    result = connection.execute(text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='user' AND name='idx_user_spotify_id';")).fetchone()
                    if not result:
                        print("Adding index 'idx_user_spotify_id' to 'user.spotify_id'.")
                        connection.execute(text('CREATE UNIQUE INDEX idx_user_spotify_id ON user (spotify_id) WHERE spotify_id IS NOT NULL;'))
                        connection.commit()
                        print("Added unique index 'idx_user_spotify_id'.")
                    else:
                        print("Index 'idx_user_spotify_id' already exists.")
            except Exception as e:
                print(f"Could not create index on spotify_id (this might be okay if using a different DB or if it exists): {e}")

            print(f"Migration {migration_name} completed successfully.")
            return True
            
        except Exception as e:
            print(f"Error during migration {migration_name}: {e}")
            # db.session.rollback() # Not needed with raw SQL execution and individual commits
            return False

if __name__ == '__main__':
    # This allows running the migration script directly
    # Ensure your Flask app and db are initialized correctly
    if not run_migration():
        sys.exit(1)
