"""Add dropbox_export_path column to User model

Revision ID: add_dropbox_export_path
Revises: f83a512b9c47
Create Date: 2025-05-08
"""
import logging
from sqlalchemy import text, inspect

def run_migration():
    """
    Add dropbox_export_path column to the User table if it doesn't exist.
    """
    try:
        from musicround import db
        changes_made = False
        try:
            inspector = inspect(db.engine)
            existing_columns = [column['name'] for column in inspector.get_columns('user')]
            with db.engine.connect() as conn:
                if 'dropbox_export_path' not in existing_columns:
                    conn.execute(text('ALTER TABLE user ADD COLUMN dropbox_export_path TEXT'))
                    conn.commit()
                    changes_made = True
        except Exception as e:
            logging.error(f"Error in migration: {str(e)}")
            return False
        if changes_made:
            logging.info("Migration completed successfully")
            return True
        else:
            logging.info("No changes were needed")
            return None
    except ImportError:
        import sqlite3
        import os
        logging.info("Falling back to direct SQLite connection")
        try:
            db_path = os.environ.get('DATABASE_PATH', '/data/song_data.db')
            if not os.path.exists(db_path):
                possible_paths = [
                    './instance/musicround.db',
                    '/app/instance/musicround.db',
                    '/data/song_data.db',
                    './song_data.db',
                    os.path.join(os.path.dirname(os.path.dirname(__file__)), 'instance', 'musicround.db')
                ]
                for path in possible_paths:
                    if os.path.exists(path):
                        db_path = path
                        break
                else:
                    logging.warning(f"Database not found at any of the possible paths")
                    return False
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(user)")
            columns = [column[1] for column in cursor.fetchall()]
            if 'dropbox_export_path' not in columns:
                cursor.execute("ALTER TABLE user ADD COLUMN dropbox_export_path TEXT")
                conn.commit()
                conn.close()
                logging.info("Migration completed successfully")
                return True
            else:
                conn.close()
                logging.info("Column already exists: dropbox_export_path")
                return None
        except Exception as e:
            logging.error(f"Migration add_dropbox_export_path failed: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return False

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    run_migration()
