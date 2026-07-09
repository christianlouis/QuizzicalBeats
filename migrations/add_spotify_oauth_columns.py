import sys
import os
import contextlib
from sqlalchemy import text

from musicround import db, create_app

# Migration name (used for logging and tracking)
migration_name = os.path.splitext(os.path.basename(__file__))[0]


def _quote_identifier(engine, identifier):
    return engine.dialect.identifier_preparer.quote(identifier)


def _add_user_column(connection, column_definition):
    user_table = _quote_identifier(db.engine, "user")
    connection.execute(text(f"ALTER TABLE {user_table} ADD COLUMN {column_definition}"))


def _index_exists(inspector, index_name):
    return any(index.get("name") == index_name for index in inspector.get_indexes("user"))


def _create_spotify_id_index(connection):
    user_table = _quote_identifier(db.engine, "user")
    spotify_id = _quote_identifier(db.engine, "spotify_id")
    index_name = _quote_identifier(db.engine, "idx_user_spotify_id")
    if connection.dialect.name.lower() in {"mysql", "mariadb"}:
        connection.execute(
            text(f"CREATE UNIQUE INDEX {index_name} ON {user_table} ({spotify_id})")
        )
        return

    connection.execute(
        text(
            f"CREATE UNIQUE INDEX {index_name} ON {user_table} ({spotify_id}) "
            f"WHERE {spotify_id} IS NOT NULL"
        )
    )


def run_migration():
    # Check if an app context already exists (e.g., if called from within Flask app)
    from flask import current_app
    try:
        app = current_app._get_current_object()
        app_context_needed = False
    except Exception:
        app = create_app()
        app_context_needed = True

    context_manager = (
        app.app_context() if app_context_needed else contextlib.nullcontext()
    )
    with context_manager:
        try:
            print(f"Starting migration: {migration_name}")

            # Use raw SQL for schema changes to avoid issues with model definitions
            # that might already expect the columns to exist.
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('user')]

            # COLUMN NAMING STRATEGY EXPLANATION:
            # ==================================
            # This migration adds 'spotify_id' as the standardized column name
            # for Spotify user IDs.
            # The chosen strategy is to use 'spotify_id' consistently throughout the application
            # for all Spotify-related user identification, rather than a generic 'oauth_id'.
            #
            # Reasoning:
            # 1. Consistency: All OAuth provider columns follow the pattern '{provider}_id'
            #    (e.g., google_id, authentik_id, dropbox_id, spotify_id)
            # 2. Clarity: 'spotify_id' explicitly indicates this field stores Spotify user IDs
            # 3. Maintainability: Future developers can immediately understand the purpose
            # 4. Extensibility: Allows for multiple OAuth providers without column name conflicts
            #
            # This approach avoids generic 'oauth_id' which could be ambiguous when supporting
            # multiple OAuth providers. Each provider gets its own dedicated ID column.

            if 'spotify_id' in columns and 'spotify_id' not in columns:
                # NOTE: This condition will never be true - kept for historical reference
                # If there was ever an 'oauth_id' column that needed renaming to 'spotify_id',
                # this would be the place to handle it. However, we've chosen to implement
                # 'spotify_id' from the start for clarity and consistency.
                print(
                    "Column 'spotify_id' exists. It will be kept for now. "
                    "Adding 'spotify_id'."
                )

            if 'spotify_id' not in columns:
                print("Adding column 'spotify_id' to 'user' table.")
                with db.engine.connect() as connection:
                    _add_user_column(connection, "spotify_id VARCHAR(100)")
                    connection.commit()
                print("Added 'spotify_id'.")
            else:
                print("Column 'spotify_id' already exists.")

            if 'spotify_token' not in columns:
                print("Adding column 'spotify_token' to 'user' table.")
                with db.engine.connect() as connection:
                    _add_user_column(connection, "spotify_token TEXT")
                    connection.commit()
                print("Added 'spotify_token'.")
            else:
                print("Column 'spotify_token' already exists.")

            if 'spotify_refresh_token' not in columns:
                print("Adding column 'spotify_refresh_token' to 'user' table.")
                with db.engine.connect() as connection:
                    _add_user_column(connection, "spotify_refresh_token TEXT")
                    connection.commit()
                print("Added 'spotify_refresh_token'.")
            else:
                print("Column 'spotify_refresh_token' already exists.")

            if 'spotify_token_expiry' not in columns:
                print("Adding column 'spotify_token_expiry' to 'user' table.")
                with db.engine.connect() as connection:
                    _add_user_column(connection, "spotify_token_expiry DATETIME")
                    connection.commit()
                print("Added 'spotify_token_expiry'.")
            else:
                print("Column 'spotify_token_expiry' already exists.")

            # Add index to spotify_id if it doesn't exist
            # Index creation syntax can vary between DBs (e.g., SQLite vs PostgreSQL)
            # SQLAlchemy model indexes would be cleaner, but this manual
            # migration has to upgrade existing deployments in place.
            # but for a manual script:
            try:
                with db.engine.connect() as connection:
                    if not _index_exists(inspector, "idx_user_spotify_id"):
                        print(
                            "Adding index 'idx_user_spotify_id' to "
                            "'user.spotify_id'."
                        )
                        _create_spotify_id_index(connection)
                        connection.commit()
                        print("Added unique index 'idx_user_spotify_id'.")
                    else:
                        print("Index 'idx_user_spotify_id' already exists.")
            except Exception as e:
                print(
                    "Could not create index on spotify_id "
                    "(this might be okay if using a different DB or if it exists): "
                    f"{e}"
                )

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
