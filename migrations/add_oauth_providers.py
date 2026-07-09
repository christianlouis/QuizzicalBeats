"""
Migration script to add Google and Authentik OAuth fields to the User table
"""
import logging
from sqlalchemy import text, inspect

logger = logging.getLogger(__name__)
POSTGRES_MIGRATION_LOCK_ID = 472814770501


def _quote_identifier(engine, identifier):
    return engine.dialect.identifier_preparer.quote(identifier)


def _add_column_sql(engine, table_name, column_definition):
    return text(
        f"ALTER TABLE {_quote_identifier(engine, table_name)} "
        f"ADD COLUMN {column_definition}"
    )


def _set_auth_provider_default_sql(engine):
    user_table = _quote_identifier(engine, "user")
    auth_provider = _quote_identifier(engine, "auth_provider")
    return text(
        f"UPDATE {user_table} SET {auth_provider} = 'local' "
        f"WHERE {auth_provider} IS NULL"
    )


def _acquire_postgres_migration_lock(conn):
    if conn.dialect.name.lower() != "postgresql":
        return False
    conn.execute(text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": POSTGRES_MIGRATION_LOCK_ID})
    return True


def _release_postgres_migration_lock(conn):
    if conn.dialect.name.lower() == "postgresql":
        conn.execute(
            text("SELECT pg_advisory_unlock(:lock_id)"),
            {"lock_id": POSTGRES_MIGRATION_LOCK_ID},
        )


def _password_hash_is_nullable(inspector):
    for column in inspector.get_columns("user"):
        if column["name"] == "password_hash":
            return bool(column.get("nullable", True))
    return True


def _drop_password_hash_not_null(engine, conn):
    if engine.dialect.name == "sqlite":
        return _drop_password_hash_not_null_sqlite(conn)

    user_table = _quote_identifier(engine, "user")
    password_hash = _quote_identifier(engine, "password_hash")
    conn.execute(
        text(f"ALTER TABLE {user_table} ALTER COLUMN {password_hash} DROP NOT NULL")
    )
    conn.commit()
    return True


def _drop_password_hash_not_null_sqlite(conn):
    result = conn.execute(text("PRAGMA table_info('user')"))
    columns_info = result.fetchall()

    is_nullable = False
    for col in columns_info:
        if col[1] == 'password_hash' and col[3] == 0:  # 0 means nullable
            is_nullable = True
            break

    if is_nullable:
        return False

    columns = []
    for col_info in columns_info:
        name = col_info[1]
        type_name = col_info[2]
        not_null = "NOT NULL" if col_info[3] == 1 and name != "password_hash" else ""
        pk = "PRIMARY KEY" if col_info[5] == 1 else ""
        columns.append(f"{name} {type_name} {pk} {not_null}".strip())

    column_defs = ", ".join(columns)
    conn.execute(text(f'CREATE TABLE user_temp ({column_defs})'))
    conn.execute(text('INSERT INTO user_temp SELECT * FROM user'))
    conn.execute(text('DROP TABLE user'))
    conn.execute(text('ALTER TABLE user_temp RENAME TO user'))
    conn.commit()
    return True


def run_migration():
    """
    Add new columns to the User table for Google and Authentik OAuth integration
    Returns:
    - True: if changes were made successfully
    - None: if no changes were needed (already up to date)
    - False: if errors occurred
    """
    from musicround import db

    # Track changes made
    changes_made = False

    try:
        # Connect to the database
        engine = db.engine
        # Use connection for executing SQL statements
        with db.engine.connect() as conn:
            lock_acquired = _acquire_postgres_migration_lock(conn)
            try:
                inspector = inspect(conn)
                existing_columns = [
                    column['name'] for column in inspector.get_columns('user')
                ]

                # Add auth_provider column if it doesn't exist
                if 'auth_provider' not in existing_columns:
                    logger.info("Adding auth_provider column")
                    try:
                        conn.execute(
                            _add_column_sql(engine, "user", "auth_provider VARCHAR(20)")
                        )
                        # Set default value for existing rows
                        conn.execute(_set_auth_provider_default_sql(engine))
                        conn.commit()
                        changes_made = True
                        logger.info("Added auth_provider column")
                    except Exception as e:
                        logger.error(f"Error adding auth_provider column: {str(e)}")

                # Add Google OAuth columns
                if 'google_id' not in existing_columns:
                    logger.info("Adding google_id column")
                    try:
                        conn.execute(
                            _add_column_sql(engine, "user", "google_id VARCHAR(100)")
                        )
                        conn.commit()
                        changes_made = True
                        logger.info("Added google_id column")
                    except Exception as e:
                        logger.error(f"Error adding google_id column: {str(e)}")

                if 'google_token' not in existing_columns:
                    logger.info("Adding google_token column")
                    try:
                        conn.execute(_add_column_sql(engine, "user", "google_token TEXT"))
                        conn.commit()
                        changes_made = True
                        logger.info("Added google_token column")
                    except Exception as e:
                        logger.error(f"Error adding google_token column: {str(e)}")

                if 'google_refresh_token' not in existing_columns:
                    logger.info("Adding google_refresh_token column")
                    try:
                        conn.execute(
                            _add_column_sql(engine, "user", "google_refresh_token TEXT")
                        )
                        conn.commit()
                        changes_made = True
                        logger.info("Added google_refresh_token column")
                    except Exception as e:
                        logger.error(f"Error adding google_refresh_token column: {str(e)}")

                # Add Authentik OAuth columns
                if 'authentik_id' not in existing_columns:
                    logger.info("Adding authentik_id column")
                    try:
                        conn.execute(
                            _add_column_sql(engine, "user", "authentik_id VARCHAR(100)")
                        )
                        conn.commit()
                        changes_made = True
                        logger.info("Added authentik_id column")
                    except Exception as e:
                        logger.error(f"Error adding authentik_id column: {str(e)}")

                if 'authentik_token' not in existing_columns:
                    logger.info("Adding authentik_token column")
                    try:
                        conn.execute(
                            _add_column_sql(engine, "user", "authentik_token TEXT")
                        )
                        conn.commit()
                        changes_made = True
                        logger.info("Added authentik_token column")
                    except Exception as e:
                        logger.error(f"Error adding authentik_token column: {str(e)}")

                if 'authentik_refresh_token' not in existing_columns:
                    logger.info("Adding authentik_refresh_token column")
                    try:
                        conn.execute(
                            _add_column_sql(
                                engine, "user", "authentik_refresh_token TEXT"
                            )
                        )
                        conn.commit()
                        changes_made = True
                        logger.info("Added authentik_refresh_token column")
                    except Exception as e:
                        logger.error(
                            f"Error adding authentik_refresh_token column: {str(e)}"
                        )

                # Make password_hash nullable for OAuth-only users
                try:
                    inspector = inspect(conn)
                    if not _password_hash_is_nullable(inspector):
                        logger.info("Modifying password_hash to be nullable")
                        _drop_password_hash_not_null(engine, conn)
                        changes_made = True
                        logger.info(
                            "Made password_hash column nullable for OAuth-only users"
                        )
                    else:
                        logger.info("password_hash is already nullable")
                except Exception as e:
                    logger.error(f"Error modifying password_hash column: {str(e)}")
            finally:
                if lock_acquired:
                    _release_postgres_migration_lock(conn)

    except Exception as e:
        logger.error(f"Error in migration: {str(e)}")
        return False  # Return False for errors

    # Report results
    if changes_made:
        logger.info("Migration completed successfully")
        return True  # Changes were made successfully
    else:
        logger.info("No changes were needed")
        return None  # No changes were needed (database is already up to date)
