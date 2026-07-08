"""Add structured result metadata to ImportJobRecord."""

import logging

from sqlalchemy import inspect, text


def run_migration():
    try:
        from musicround import db

        inspector = inspect(db.engine)
        existing_columns = [column["name"] for column in inspector.get_columns("import_job_record")]
        if "result_metadata" in existing_columns:
            logging.info("No changes were needed")
            return None

        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE import_job_record ADD COLUMN result_metadata TEXT"))
            conn.commit()

        logging.info("Migration add_import_job_result_metadata completed successfully")
        return True
    except Exception as exc:
        logging.error("Migration add_import_job_result_metadata failed: %s", exc)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
