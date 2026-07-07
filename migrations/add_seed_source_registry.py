"""Add seed source registry tables for chart and festival ingestion planning."""

import logging

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)


def _quote(identifier, preparer):
    return preparer.quote(identifier)


def _table_exists(inspector, table_name):
    return table_name in set(inspector.get_table_names())


def _columns(inspector, table_name):
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_exists(inspector, table_name, index_name):
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def _foreign_key_exists(inspector, table_name, referred_table, constrained_columns):
    expected_columns = set(constrained_columns)
    for foreign_key in inspector.get_foreign_keys(table_name):
        if foreign_key.get("referred_table") != referred_table:
            continue
        if set(foreign_key.get("constrained_columns") or []) == expected_columns:
            return True
    return False


def _create_index(conn, inspector, table_name, index_name, columns):
    if _index_exists(inspector, table_name, index_name):
        return False
    preparer = conn.dialect.identifier_preparer
    quoted_table = _quote(table_name, preparer)
    quoted_index = _quote(index_name, preparer)
    quoted_columns = ", ".join(_quote(column, preparer) for column in columns)
    conn.execute(text(f"CREATE INDEX {quoted_index} ON {quoted_table} ({quoted_columns})"))
    return True


def _create_seed_source_run_table(conn, table_name="seed_source_run"):
    preparer = conn.dialect.identifier_preparer
    quoted_table = _quote(table_name, preparer)
    conn.execute(
        text(
            f"""
            CREATE TABLE {quoted_table} (
                id INTEGER PRIMARY KEY,
                seed_source_id INTEGER NOT NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'planned',
                started_at DATETIME NOT NULL,
                completed_at DATETIME,
                songs_seen INTEGER NOT NULL DEFAULT 0,
                songs_imported INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                notes TEXT,
                FOREIGN KEY(seed_source_id) REFERENCES seed_source(id) ON DELETE CASCADE
            )
            """
        )
    )


def _rebuild_seed_source_run_with_foreign_key(conn):
    """Recreate legacy seed_source_run with the model's foreign key constraint."""
    temp_table = "seed_source_run_with_fk"
    preparer = conn.dialect.identifier_preparer
    quoted_temp = _quote(temp_table, preparer)
    quoted_run = _quote("seed_source_run", preparer)
    _create_seed_source_run_table(conn, temp_table)
    conn.execute(
        text(
            f"""
            INSERT INTO {quoted_temp} (
                id,
                seed_source_id,
                status,
                started_at,
                completed_at,
                songs_seen,
                songs_imported,
                error_message,
                notes
            )
            SELECT
                run.id,
                run.seed_source_id,
                run.status,
                run.started_at,
                run.completed_at,
                run.songs_seen,
                run.songs_imported,
                run.error_message,
                run.notes
            FROM {quoted_run} AS run
            WHERE EXISTS (
                SELECT 1
                FROM seed_source AS source
                WHERE source.id = run.seed_source_id
            )
            """
        )
    )
    conn.execute(text(f"DROP TABLE {quoted_run}"))
    conn.execute(text(f"ALTER TABLE {quoted_temp} RENAME TO {quoted_run}"))
    return True


def run_migration():
    """Backfill seed source registry tables on existing databases."""
    try:
        from musicround import db

        changes_made = False
        inspector = inspect(db.engine)
        with db.engine.connect() as conn:
            if not _table_exists(inspector, "seed_source"):
                conn.execute(
                    text(
                        """
                        CREATE TABLE seed_source (
                            id INTEGER PRIMARY KEY,
                            name VARCHAR(200) NOT NULL,
                            source_type VARCHAR(50) NOT NULL,
                            provider VARCHAR(100),
                            url VARCHAR(500),
                            cadence VARCHAR(50),
                            active BOOLEAN NOT NULL DEFAULT 1,
                            priority INTEGER NOT NULL DEFAULT 100,
                            notes TEXT,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME,
                            UNIQUE(name, provider)
                        )
                        """
                    )
                )
                changes_made = True

            inspector = inspect(db.engine)
            if _table_exists(inspector, "seed_source"):
                source_columns = _columns(inspector, "seed_source")
                if "notes" not in source_columns:
                    conn.execute(text("ALTER TABLE seed_source ADD COLUMN notes TEXT"))
                    changes_made = True
                if "updated_at" not in source_columns:
                    conn.execute(text("ALTER TABLE seed_source ADD COLUMN updated_at DATETIME"))
                    changes_made = True

            inspector = inspect(db.engine)
            if not _table_exists(inspector, "seed_source_run"):
                _create_seed_source_run_table(conn)
                changes_made = True
            elif not _foreign_key_exists(inspector, "seed_source_run", "seed_source", ["seed_source_id"]):
                _rebuild_seed_source_run_with_foreign_key(conn)
                changes_made = True

            inspector = inspect(db.engine)
            for table_name, index_name, columns in (
                ("seed_source", "idx_seed_source_type_active", ["source_type", "active", "priority"]),
                (
                    "seed_source_run",
                    "idx_seed_source_run_source_status",
                    ["seed_source_id", "status", "started_at"],
                ),
            ):
                if table_name not in set(inspector.get_table_names()):
                    continue
                existing_columns = _columns(inspector, table_name)
                if all(column in existing_columns for column in columns):
                    changes_made = _create_index(conn, inspector, table_name, index_name, columns) or changes_made

            if changes_made:
                conn.commit()

        return True if changes_made else None
    except Exception as exc:
        logger.error("Migration add_seed_source_registry failed: %s", exc)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
