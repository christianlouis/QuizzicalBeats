"""Add scheduled email fields to RoundExport."""

import logging

from sqlalchemy import inspect, text


def run_migration():
    try:
        from musicround import db

        inspector = inspect(db.engine)
        existing_columns = [column["name"] for column in inspector.get_columns("round_export")]
        columns = {
            "scheduled_for": "DATETIME",
            "processed_at": "DATETIME",
            "subject": "VARCHAR(500)",
            "body_text": "TEXT",
        }

        changes_made = False
        with db.engine.connect() as conn:
            for column_name, column_type in columns.items():
                if column_name in existing_columns:
                    continue
                conn.execute(
                    text(f"ALTER TABLE round_export ADD COLUMN {column_name} {column_type}")
                )
                changes_made = True
            if changes_made:
                conn.commit()

        if changes_made:
            logging.info("Migration add_round_export_schedule completed successfully")
            return True
        logging.info("No changes were needed")
        return None
    except Exception as exc:
        logging.error("Migration add_round_export_schedule failed: %s", exc)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
