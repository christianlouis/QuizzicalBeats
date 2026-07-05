"""Add generated-asset status fields to Round."""

import logging

from sqlalchemy import inspect, text


def run_migration():
    try:
        from musicround import db

        inspector = inspect(db.engine)
        existing_columns = [column["name"] for column in inspector.get_columns("round")]
        columns = {
            "mp3_generated": "BOOLEAN DEFAULT 0",
            "pdf_generated": "BOOLEAN DEFAULT 0",
            "last_generated_at": "DATETIME",
        }

        changes_made = False
        with db.engine.connect() as conn:
            for column_name, column_type in columns.items():
                if column_name in existing_columns:
                    continue
                conn.execute(text(f"ALTER TABLE round ADD COLUMN {column_name} {column_type}"))
                changes_made = True
            if changes_made:
                conn.commit()

        if changes_made:
            logging.info("Migration add_round_generation_status completed successfully")
            return True
        logging.info("No changes were needed")
        return None
    except Exception as exc:
        logging.error("Migration add_round_generation_status failed: %s", exc)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
