"""Add planned quiz rounds for agentic scheduling workflows."""

import logging

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)


def _table_exists(inspector, table_name):
    return table_name in set(inspector.get_table_names())


def _index_exists(inspector, table_name, index_name):
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def _create_index(conn, inspector, table_name, index_name, columns):
    if _index_exists(inspector, table_name, index_name):
        return False
    preparer = conn.dialect.identifier_preparer
    quoted_table = preparer.quote(table_name)
    quoted_index = preparer.quote(index_name)
    quoted_columns = ", ".join(preparer.quote(column) for column in columns)
    conn.execute(text(f"CREATE INDEX {quoted_index} ON {quoted_table} ({quoted_columns})"))
    return True


def run_migration():
    """Create the planned quiz round table on existing databases."""
    try:
        from musicround import db

        inspector = inspect(db.engine)
        changes_made = False
        with db.engine.connect() as conn:
            if not _table_exists(inspector, "planned_quiz_round"):
                conn.execute(
                    text(
                        """
                        CREATE TABLE planned_quiz_round (
                            id INTEGER PRIMARY KEY,
                            quiz_date DATETIME NOT NULL,
                            quizmaster_id INTEGER,
                            theme VARCHAR(200),
                            brief TEXT,
                            source_playlist_url VARCHAR(500),
                            due_at DATETIME,
                            status VARCHAR(20) NOT NULL DEFAULT 'planned',
                            round_id INTEGER,
                            export_id INTEGER,
                            created_at DATETIME,
                            updated_at DATETIME
                        )
                        """
                    )
                )
                changes_made = True

            inspector = inspect(db.engine)
            if _table_exists(inspector, "planned_quiz_round"):
                for index_name, columns in (
                    ("idx_planned_quiz_round_status_due", ["status", "due_at", "quiz_date"]),
                    ("idx_planned_quiz_round_quizmaster_date", ["quizmaster_id", "quiz_date"]),
                ):
                    changes_made = (
                        _create_index(conn, inspector, "planned_quiz_round", index_name, columns)
                        or changes_made
                    )

            if changes_made:
                conn.commit()

        return True if changes_made else None
    except Exception as exc:
        logger.error("Migration add_planned_quiz_rounds failed: %s", exc)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
