"""Add Dropbox OAuth fields to User model

Revision ID: f83a512b9c47
Revises: e7c912b4d835
Create Date: 2025-05-08 14:30:45.891234

"""
from alembic import op
import sqlalchemy as sa
import logging
from sqlalchemy import text, inspect
from datetime import datetime

# revision identifiers, used by Alembic.
revision = 'f83a512b9c47'
down_revision = 'e7c912b4d835'  # previous migration was add_tag_system
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)

def upgrade():
    # Add Dropbox OAuth columns to user table
    op.add_column('user', sa.Column('dropbox_id', sa.String(100), nullable=True))
    op.add_column('user', sa.Column('dropbox_token', sa.Text(), nullable=True))
    op.add_column('user', sa.Column('dropbox_refresh_token', sa.Text(), nullable=True))
    op.add_column('user', sa.Column('dropbox_token_expiry', sa.DateTime(), nullable=True))

def downgrade():
    # Remove Dropbox OAuth columns
    op.drop_column('user', 'dropbox_id')
    op.drop_column('user', 'dropbox_token')
    op.drop_column('user', 'dropbox_refresh_token')
    op.drop_column('user', 'dropbox_token_expiry')

def run_migration():
    """
    Add Dropbox OAuth fields to the User table if they don't exist.
    """
    try:
        from musicround import db
        
        # Track changes made
        changes_made = False
        
        try:
            # Connect to the database
            inspector = inspect(db.engine)
            existing_columns = [column['name'] for column in inspector.get_columns('user')]
            
            # Use connection for executing SQL statements
            with db.engine.connect() as conn:
                # Add Dropbox OAuth columns
                if 'dropbox_id' not in existing_columns:
                    logger.info("Adding dropbox_id column")
                    try:
                        conn.execute(text('ALTER TABLE user ADD COLUMN dropbox_id VARCHAR(100)'))
                        conn.commit()
                        changes_made = True
                        logger.info("Added dropbox_id column")
                    except Exception as e:
                        logger.error(f"Error adding dropbox_id column: {str(e)}")
                    
                if 'dropbox_token' not in existing_columns:
                    logger.info("Adding dropbox_token column")
                    try:
                        conn.execute(text('ALTER TABLE user ADD COLUMN dropbox_token TEXT'))
                        conn.commit()
                        changes_made = True
                        logger.info("Added dropbox_token column")
                    except Exception as e:
                        logger.error(f"Error adding dropbox_token column: {str(e)}")
                    
                if 'dropbox_refresh_token' not in existing_columns:
                    logger.info("Adding dropbox_refresh_token column")
                    try:
                        conn.execute(text('ALTER TABLE user ADD COLUMN dropbox_refresh_token TEXT'))
                        conn.commit()
                        changes_made = True
                        logger.info("Added dropbox_refresh_token column")
                    except Exception as e:
                        logger.error(f"Error adding dropbox_refresh_token column: {str(e)}")
                
                if 'dropbox_token_expiry' not in existing_columns:
                    logger.info("Adding dropbox_token_expiry column")
                    try:
                        conn.execute(text('ALTER TABLE user ADD COLUMN dropbox_token_expiry DATETIME'))
                        conn.commit()
                        changes_made = True
                        logger.info("Added dropbox_token_expiry column")
                    except Exception as e:
                        logger.error(f"Error adding dropbox_token_expiry column: {str(e)}")
            
        except Exception as e:
            logger.error(f"Error in migration: {str(e)}")
            return False  # Return False for errors

        # Report results
        if changes_made:
            logger.info("Migration completed successfully")
            return True  # Changes were made successfully
        else:
            logger.info("No changes were needed")
            return None  # No changes were needed (database is already up to date)
            
    except ImportError:
        # If we can't import the db object, fall back to SQLite direct connection
        import sqlite3
        import os
        
        logger.info("Falling back to direct SQLite connection")
        
        # Try to get the database path from environment or standard locations
        try:
            # Try environment variable
            db_path = os.environ.get('DATABASE_PATH', '/data/song_data.db')
            
            # If that doesn't exist, try other possible paths
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
                        logger.info(f"Found database at: {db_path}")
                        break
                else:
                    logger.warning(f"Database not found at any of the possible paths")
                    return False
            
            # Connect to the database
            logger.info(f"Connecting to database at: {db_path}")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get existing columns
            cursor.execute("PRAGMA table_info(user)")
            columns = [column[1] for column in cursor.fetchall()]
            
            # Define the new columns to add
            new_columns = [
                ("dropbox_id", "VARCHAR(100)"),
                ("dropbox_token", "TEXT"),
                ("dropbox_refresh_token", "TEXT"),
                ("dropbox_token_expiry", "DATETIME")
            ]
            
            # Add each column if it doesn't exist
            changes_made = False
            for column_name, column_type in new_columns:
                if column_name not in columns:
                    sql = f"ALTER TABLE user ADD COLUMN {column_name} {column_type}"
                    cursor.execute(sql)
                    logger.info(f"Added column: {column_name} {column_type}")
                    changes_made = True
                else:
                    logger.info(f"Column already exists: {column_name}")
            
            # Commit changes and close connection
            conn.commit()
            conn.close()
            
            if changes_made:
                logger.info("Migration completed successfully")
                return True
            else:
                logger.info("No changes were needed")
                return None
                
        except Exception as e:
            logger.error(f"Migration add_dropbox_oauth failed: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False

if __name__ == "__main__":
    # Set up logging when run directly
    logging.basicConfig(level=logging.INFO)
    run_migration()