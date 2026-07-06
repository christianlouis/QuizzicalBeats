"""Add retry tracking fields to ImportJobRecord."""

import logging

from sqlalchemy import inspect, text


def run_migration():
    try:
        from musicround import db

        inspector = inspect(db.engine)
        existing_columns = [column["name"] for column in inspector.get_columns("import_job_record")]
        columns = {
            "attempt_count": "INTEGER DEFAULT 0",
            "max_attempts": "INTEGER DEFAULT 3",
        }

        changes_made = False
        with db.engine.connect() as conn:
            for column_name, column_type in columns.items():
                if column_name in existing_columns:
                    continue
                conn.execute(
                    text(f"ALTER TABLE import_job_record ADD COLUMN {column_name} {column_type}")
                )
                changes_made = True
            conn.execute(
                text("UPDATE import_job_record SET attempt_count = 0 WHERE attempt_count IS NULL")
            )
            conn.execute(
                text("UPDATE import_job_record SET max_attempts = 3 WHERE max_attempts IS NULL")
            )
            conn.commit()

        if changes_made:
            logging.info("Migration add_import_job_attempts completed successfully")
            return True
        logging.info("No changes were needed")
        return None
    except Exception as exc:
        logging.error("Migration add_import_job_attempts failed: %s", exc)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
