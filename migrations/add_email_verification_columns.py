"""Add local account email-verification fields."""

import logging

from sqlalchemy import inspect, text


def run_migration():
    try:
        from musicround import db

        inspector = inspect(db.engine)
        columns = {column["name"] for column in inspector.get_columns("user")}
        statements = []
        if "email_verification_token" not in columns:
            statements.append("ALTER TABLE \"user\" ADD COLUMN email_verification_token VARCHAR(100)")
        if "email_verification_expiry" not in columns:
            statements.append("ALTER TABLE \"user\" ADD COLUMN email_verification_expiry TIMESTAMP")
        if "email_verified_at" not in columns:
            statements.append("ALTER TABLE \"user\" ADD COLUMN email_verified_at TIMESTAMP")
        if not statements:
            logging.info("No changes were needed")
            return None

        with db.engine.connect() as conn:
            for statement in statements:
                conn.execute(text(statement))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_email_verification_token ON \"user\" (email_verification_token)"))
            conn.commit()
        logging.info("Added local account email-verification fields")
        return True
    except Exception as exc:
        logging.error("add_email_verification_columns failed: %s", exc)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
