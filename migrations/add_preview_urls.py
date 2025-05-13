"""Add multiple preview URLs and cover URLs to Song model

Revision ID: d82c9a4f1e56
Revises: a7cb4e9f8d21
Create Date: 2023-06-11 14:23:45.678901

"""
from alembic import op
import sqlalchemy as sa
import sqlite3
import os
import logging

# revision identifiers, used by Alembic.
revision = 'd82c9a4f1e56'
down_revision = 'a7cb4e9f8d21'  # replace with your previous migration id
branch_labels = None
depends_on = None

def upgrade():
    # Add new columns for preview URLs from different sources
    op.add_column('song', sa.Column('spotify_preview_url', sa.String(255), nullable=True))
    op.add_column('song', sa.Column('deezer_preview_url', sa.String(255), nullable=True))
    op.add_column('song', sa.Column('apple_preview_url', sa.String(255), nullable=True))
    op.add_column('song', sa.Column('youtube_preview_url', sa.String(255), nullable=True))
    
    # Add new columns for cover URLs from different services
    op.add_column('song', sa.Column('spotify_cover_url', sa.String(255), nullable=True))
    op.add_column('song', sa.Column('deezer_cover_url', sa.String(255), nullable=True))
    op.add_column('song', sa.Column('apple_cover_url', sa.String(255), nullable=True))
    
    # Add a column for additional data as JSON
    op.add_column('song', sa.Column('additional_data', sa.Text(), nullable=True))

def downgrade():
    # Remove the new columns
    op.drop_column('song', 'spotify_preview_url')
    op.drop_column('song', 'deezer_preview_url')
    op.drop_column('song', 'apple_preview_url')
    op.drop_column('song', 'youtube_preview_url')
    op.drop_column('song', 'spotify_cover_url')
    op.drop_column('song', 'deezer_cover_url')
    op.drop_column('song', 'apple_cover_url')
    op.drop_column('song', 'additional_data')

def run_migration():
    """
    Add platform-specific preview URL columns to the song table if they don't exist.
    """
    logger = logging.getLogger(__name__)
    logger.info("Running migration: add_preview_urls")
    
    # Try to get the database path from Flask config first
    try:
        from flask import current_app
        if current_app and current_app.config.get('SQLALCHEMY_DATABASE_URI'):
            # Extract path from URI
            db_uri = current_app.config['SQLALCHEMY_DATABASE_URI']
            if db_uri.startswith('sqlite:///'):
                db_path = db_uri[10:]  # Remove 'sqlite:///'
                logger.info(f"Got database path from Flask config: {db_path}")
            else:
                # Use DATABASE_PATH if available
                db_path = current_app.config.get('DATABASE_PATH', '/data/song_data.db')
                logger.info(f"Using DATABASE_PATH: {db_path}")
        else:
            # If Flask isn't running, try Docker standard path
            db_path = '/data/song_data.db'
            logger.info(f"Flask not available, using default path: {db_path}")
    except Exception as e:
        # Fallbacks in case Flask isn't available
        logger.warning(f"Could not get path from Flask: {str(e)}")
        
        # Try environment variable
        db_path = os.environ.get('DATABASE_PATH', '/data/song_data.db')
        logger.info(f"Using DATABASE_PATH from environment: {db_path}")
    
    if not os.path.exists(db_path):
        logger.warning(f"Database not found at {db_path}")
        return False
        
    try:
        # Connect to the database
        logger.info(f"Connecting to database at: {db_path}")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get existing columns
        cursor.execute("PRAGMA table_info(song)")
        columns = [column[1] for column in cursor.fetchall()]
        
        # Define the new columns to add
        new_columns = [
            ("spotify_preview_url", "VARCHAR(500)"),
            ("deezer_preview_url", "VARCHAR(500)"),
            ("apple_preview_url", "VARCHAR(500)"),
            ("youtube_preview_url", "VARCHAR(500)"),
            ("spotify_cover_url", "VARCHAR(500)"),
            ("deezer_cover_url", "VARCHAR(500)"),
            ("apple_cover_url", "VARCHAR(500)"),
            ("additional_data", "TEXT")
        ]
        
        # Add each column if it doesn't exist
        for column_name, column_type in new_columns:
            if column_name not in columns:
                sql = f"ALTER TABLE song ADD COLUMN {column_name} {column_type}"
                cursor.execute(sql)
                logger.info(f"Added column: {column_name} {column_type}")
            else:
                logger.info(f"Column already exists: {column_name}")
        
        # Commit changes and close connection
        conn.commit()
        conn.close()
        logger.info("Migration add_preview_urls completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Migration add_preview_urls failed: {str(e)}")
        return False

if __name__ == "__main__":
    # Set up logging when run directly
    logging.basicConfig(level=logging.INFO)
    run_migration()
