import sys
import os
import contextlib
from sqlalchemy import text

from musicround import db, create_app

# Migration name (used for logging and tracking)
migration_name = os.path.splitext(os.path.basename(__file__))[0]
POSTGRES_MIGRATION_LOCK_ID = 472814770501


def _quote_identifier(engine, identifier):
    return engine.dialect.identifier_preparer.quote(identifier)


def _add_user_column(connection, column_definition):
    user_table = _quote_identifier(db.engine, "user")
    connection.execute(text(f"ALTER TABLE {user_table} ADD COLUMN {column_definition}"))


def _index_exists(inspector, index_name):
    return any(index.get("name") == index_name for index in inspector.get_indexes("user"))


def _acquire_postgres_migration_lock(connection):
    if connection.dialect.name.lower() != "postgresql":
        return False
    connection.execute(
        text("SELECT pg_advisory_lock(:lock_id)"),
        {"lock_id": POSTGRES_MIGRATION_LOCK_ID},
    )
    return True


def _release_postgres_migration_lock(connection):
    if connection.dialect.name.lower() == "postgresql":
        connection.execute(
            text("SELECT pg_advisory_unlock(:lock_id)"),
            {"lock_id": POSTGRES_MIGRATION_LOCK_ID},
        )


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
            with db.engine.connect() as connection:
                lock_acquired = _acquire_postgres_migration_lock(connection)
                try:
                    inspector = db.inspect(connection)
                    columns = [col['name'] for col in inspector.get_columns('user')]

                    if 'spotify_id' not in columns:
                        print("Adding column 'spotify_id' to 'user' table.")
                        _add_user_column(connection, "spotify_id VARCHAR(100)")
                        connection.commit()
                        print("Added 'spotify_id'.")
                    else:
                        print("Column 'spotify_id' already exists.")

                    if 'spotify_token' not in columns:
                        print("Adding column 'spotify_token' to 'user' table.")
                        _add_user_column(connection, "spotify_token TEXT")
                        connection.commit()
                        print("Added 'spotify_token'.")
                    else:
                        print("Column 'spotify_token' already exists.")

                    if 'spotify_refresh_token' not in columns:
                        print(
                            "Adding column 'spotify_refresh_token' to 'user' table."
                        )
                        _add_user_column(connection, "spotify_refresh_token TEXT")
                        connection.commit()
                        print("Added 'spotify_refresh_token'.")
                    else:
                        print("Column 'spotify_refresh_token' already exists.")

                    if 'spotify_token_expiry' not in columns:
                        print("Adding column 'spotify_token_expiry' to 'user' table.")
                        _add_user_column(connection, "spotify_token_expiry DATETIME")
                        connection.commit()
                        print("Added 'spotify_token_expiry'.")
                    else:
                        print("Column 'spotify_token_expiry' already exists.")

                    inspector = db.inspect(connection)
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
                finally:
                    if lock_acquired:
                        _release_postgres_migration_lock(connection)

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
