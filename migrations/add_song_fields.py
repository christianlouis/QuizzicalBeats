"""Add new fields to Song model

Revision ID: a7cb4e9f8d21
Revises: previous_revision_id
Create Date: 2023-06-10 12:34:56.789012

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a7cb4e9f8d21'
down_revision = 'previous_revision_id'  # replace with your previous migration id
branch_labels = None
depends_on = None

def upgrade():
    # Add new columns to the song table
    op.add_column('song', sa.Column('isrc', sa.String(50), nullable=True))
    op.add_column('song', sa.Column('album_name', sa.String(100), nullable=True))
    op.add_column('song', sa.Column('metadata_sources', sa.String(100), nullable=True))
    op.add_column('song', sa.Column('import_date', sa.DateTime, nullable=True))
    
    # Create index for ISRC
    op.create_index(op.f('ix_song_isrc'), 'song', ['isrc'], unique=False)
    
    # Increase length of existing URL columns
    op.alter_column('song', 'preview_url', type_=sa.String(255))
    op.alter_column('song', 'cover_url', type_=sa.String(255))

def downgrade():
    # Remove the new columns
    op.drop_index(op.f('ix_song_isrc'), table_name='song')
    op.drop_column('song', 'isrc')
    op.drop_column('song', 'album_name')
    op.drop_column('song', 'metadata_sources')
    op.drop_column('song', 'import_date')
    
    # Restore original column lengths
    op.alter_column('song', 'preview_url', type_=sa.String(200))
    op.alter_column('song', 'cover_url', type_=sa.String(200))

def run_migration():
    """
    Add additional song fields to the song table if they don't exist.
    """
    import sqlite3
    import os
    import logging
    
    logger = logging.getLogger(__name__)
    logger.info("Running migration: add_song_fields")
    
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
            ("album_name", "VARCHAR(200)"),
            ("metadata_sources", "VARCHAR(500)"),
            ("import_date", "DATETIME"),
            ("source", "VARCHAR(20)")
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
        logger.info("Migration add_song_fields completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Migration add_song_fields failed: {str(e)}")
        return False

if __name__ == "__main__":
    # Set up logging when run directly
    import logging
    logging.basicConfig(level=logging.INFO)
    run_migration()
