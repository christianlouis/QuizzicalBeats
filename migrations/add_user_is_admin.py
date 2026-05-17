"""
Migration script to add the is_admin flag expected by the current User model.
"""
import logging

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)


def run_migration():
    """
    Add user.is_admin and backfill it from the existing admin role assignment.
    Returns:
    - True: if changes were made successfully
    - None: if no changes were needed
    - False: if errors occurred
    """
    from musicround import db

    try:
        inspector = inspect(db.engine)
        existing_columns = [column["name"] for column in inspector.get_columns("user")]

        if "is_admin" in existing_columns:
            logger.info("is_admin column already exists")
            return None

        with db.engine.connect() as conn:
            logger.info("Adding is_admin column")
            conn.execute(text('ALTER TABLE "user" ADD COLUMN is_admin BOOLEAN DEFAULT 0'))
            conn.execute(
                text(
                    """
                    UPDATE "user"
                       SET is_admin = 1
                     WHERE id IN (
                         SELECT ur.user_id
                           FROM user_roles ur
                           JOIN role r ON r.id = ur.role_id
                          WHERE lower(r.name) = 'admin'
                     )
                    """
                )
            )
            conn.commit()

        logger.info("Added is_admin column")
        return True
    except Exception as e:
        logger.error(f"Migration add_user_is_admin failed: {str(e)}")
        return False
