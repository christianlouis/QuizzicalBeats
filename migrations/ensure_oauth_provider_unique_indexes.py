"""Add unique indexes for OAuth provider account IDs."""

import logging
from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)

PROVIDER_ID_COLUMNS = {
    "google_id": "idx_user_google_id",
    "authentik_id": "idx_user_authentik_id",
    "dropbox_id": "idx_user_dropbox_id",
}


def _index_exists(inspector, index_name):
    """Return whether the target index already exists on the user table."""
    return any(index.get("name") == index_name for index in inspector.get_indexes("user"))


def _find_duplicate_values(conn, column_name):
    """Return non-null provider IDs that would violate the new unique index."""
    return conn.execute(
        text(
            f"""
            SELECT {column_name}, COUNT(*) AS duplicate_count
            FROM user
            WHERE {column_name} IS NOT NULL
            GROUP BY {column_name}
            HAVING COUNT(*) > 1
            LIMIT 10
            """
        )
    ).fetchall()


def _normalize_empty_values(conn, column_name):
    """Convert legacy blank provider IDs to NULL before adding uniqueness."""
    query = text(f"UPDATE user SET {column_name} = NULL WHERE {column_name} = ''")
    return conn.execute(query).rowcount


def _create_unique_index(conn, column_name, index_name):
    """Create a unique provider-ID index using syntax supported by the active DB."""
    dialect_name = conn.dialect.name.lower()
    if dialect_name in {"mysql", "mariadb"}:
        conn.execute(text(f"CREATE UNIQUE INDEX {index_name} ON user ({column_name})"))
        return

    conn.execute(
        text(
            f"CREATE UNIQUE INDEX {index_name} ON user ({column_name}) "
            f"WHERE {column_name} IS NOT NULL"
        )
    )


def run_migration():
    """Create unique indexes after explicitly checking for duplicate values."""
    from musicround import db

    changes_made = False

    try:
        inspector = inspect(db.engine)
        existing_columns = {column["name"] for column in inspector.get_columns("user")}

        with db.engine.connect() as conn:
            for column_name, index_name in PROVIDER_ID_COLUMNS.items():
                if column_name not in existing_columns:
                    logger.warning(
                        "Column %s is missing; skipping unique index %s",
                        column_name,
                        index_name,
                    )
                    continue

                if _index_exists(inspector, index_name):
                    logger.info("Unique index %s already exists", index_name)
                    continue

                if _normalize_empty_values(conn, column_name):
                    changes_made = True

                duplicates = _find_duplicate_values(conn, column_name)
                if duplicates:
                    logger.error(
                        "Cannot add unique index %s because duplicate %s values exist: %s",
                        index_name,
                        column_name,
                        [(row[0], row[1]) for row in duplicates],
                    )
                    return False

                logger.info("Adding unique index %s on user.%s", index_name, column_name)
                _create_unique_index(conn, column_name, index_name)
                conn.commit()
                changes_made = True

        return True if changes_made else None
    except Exception as exc:
        logger.error("Error adding OAuth provider unique indexes: %s", exc)
        return False
