"""Add review and approval state to quiz rounds."""

import logging

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)


def _columns(inspector, table_name):
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_exists(inspector, table_name, index_name):
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def run_migration():
    """Backfill lightweight round-review workflow columns."""
    try:
        from musicround import db

        inspector = inspect(db.engine)
        if "round" not in set(inspector.get_table_names()):
            logger.info("Skipping round review migration because round table is missing")
            return None

        changes_made = False
        with db.engine.connect() as conn:
            preparer = conn.dialect.identifier_preparer
            round_table = preparer.quote("round")
            columns = _columns(inspector, "round")
            column_defs = {
                "review_status": "VARCHAR(20) DEFAULT 'draft' NOT NULL",
                "review_notes": "TEXT",
                "approved_at": "DATETIME",
                "approved_by_id": "INTEGER",
            }
            for column_name, column_type in column_defs.items():
                if column_name not in columns:
                    conn.execute(text(f"ALTER TABLE {round_table} ADD COLUMN {column_name} {column_type}"))
                    changes_made = True

            inspector = inspect(db.engine)
            columns = _columns(inspector, "round")
            if (
                {"review_status", "approved_at"}.issubset(columns)
                and not _index_exists(inspector, "round", "idx_round_review_status")
            ):
                quoted_index = preparer.quote("idx_round_review_status")
                conn.execute(
                    text(
                        f"CREATE INDEX {quoted_index} ON {round_table} "
                        "(review_status, approved_at)"
                    )
                )
                changes_made = True

            if changes_made:
                conn.commit()

        return True if changes_made else None
    except Exception as exc:
        logger.error("Migration add_round_review_workflow failed: %s", exc)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from musicround import create_app

    app = create_app()
    with app.app_context():
        run_migration()
