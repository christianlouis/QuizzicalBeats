"""Add indexes for catalog, import queue, and scheduled export lookups."""

import logging

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)

INDEXES = [
    {
        "name": "idx_song_artist_title",
        "table": "song",
        "columns": ["artist", "title"],
    },
    {
        "name": "idx_song_genre_year",
        "table": "song",
        "columns": ["genre", "year"],
    },
    {
        "name": "idx_song_usage",
        "table": "song",
        "columns": ["used_count", "last_used"],
    },
    {
        "name": "idx_round_created_at",
        "table": "round",
        "columns": ["created_at"],
    },
    {
        "name": "idx_round_generation_status",
        "table": "round",
        "columns": ["mp3_generated", "pdf_generated"],
    },
    {
        "name": "idx_round_export_schedule",
        "table": "round_export",
        "columns": ["status", "scheduled_for", "export_type"],
    },
    {
        "name": "idx_round_export_round_timestamp",
        "table": "round_export",
        "columns": ["round_id", "timestamp"],
    },
    {
        "name": "idx_import_job_claim",
        "table": "import_job_record",
        "columns": ["status", "priority", "created_at"],
    },
    {
        "name": "idx_import_job_user_status",
        "table": "import_job_record",
        "columns": ["user_id", "status", "created_at"],
    },
]


def _quote(identifier, preparer):
    return preparer.quote(identifier)


def _index_exists(inspector, table_name, index_name):
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def _table_columns(inspector, table_name):
    return {column["name"] for column in inspector.get_columns(table_name)}


def _create_index(conn, table_name, index_name, columns):
    preparer = conn.dialect.identifier_preparer
    quoted_table = _quote(table_name, preparer)
    quoted_index = _quote(index_name, preparer)
    quoted_columns = ", ".join(_quote(column, preparer) for column in columns)
    conn.execute(text(f"CREATE INDEX {quoted_index} ON {quoted_table} ({quoted_columns})"))


def run_migration():
    """Create missing query-performance indexes without touching data."""
    from musicround import db

    changes_made = False

    try:
        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())

        with db.engine.connect() as conn:
            for spec in INDEXES:
                table_name = spec["table"]
                index_name = spec["name"]
                columns = spec["columns"]

                if table_name not in existing_tables:
                    logger.info("Skipping index %s because table %s is missing", index_name, table_name)
                    continue

                if _index_exists(inspector, table_name, index_name):
                    logger.info("Index %s already exists", index_name)
                    continue

                existing_columns = _table_columns(inspector, table_name)
                missing_columns = [column for column in columns if column not in existing_columns]
                if missing_columns:
                    logger.info(
                        "Skipping index %s because columns are missing: %s",
                        index_name,
                        ", ".join(missing_columns),
                    )
                    continue

                logger.info("Creating index %s on %s", index_name, table_name)
                _create_index(conn, table_name, index_name, columns)
                changes_made = True

            if changes_made:
                conn.commit()

        return True if changes_made else None
    except Exception as exc:
        logger.error("Migration add_query_performance_indexes failed: %s", exc)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
