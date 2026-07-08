"""Add user-level notification preference flags."""

import logging

from sqlalchemy import inspect, text


def run_migration():
    try:
        from musicround import db

        inspector = inspect(db.engine)
        existing_columns = [column["name"] for column in inspector.get_columns("user_preferences")]
        if "import_job_email_notifications" in existing_columns:
            logging.info("No changes were needed")
            return None

        with db.engine.connect() as conn:
            conn.execute(
                text(
                    "ALTER TABLE user_preferences "
                    "ADD COLUMN import_job_email_notifications BOOLEAN DEFAULT 1 NOT NULL"
                )
            )
            conn.execute(
                text(
                    "UPDATE user_preferences "
                    "SET import_job_email_notifications = 1 "
                    "WHERE import_job_email_notifications IS NULL"
                )
            )
            conn.commit()

        logging.info("Migration add_user_notification_preferences completed successfully")
        return True
    except Exception as exc:
        logging.error("Migration add_user_notification_preferences failed: %s", exc)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
