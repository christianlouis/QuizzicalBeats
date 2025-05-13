"""Add tag system for songs

Revision ID: e7c912b4d835
Revises: d82c9a4f1e56
Create Date: 2025-04-22 10:34:56.789012

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e7c912b4d835'
down_revision = 'd82c9a4f1e56'  # previous migration was add_preview_urls
branch_labels = None
depends_on = None

def upgrade():
    # Create tag table
    op.create_table('tag',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    
    # Create song_tag mapping table
    op.create_table('song_tag',
        sa.Column('song_id', sa.Integer(), nullable=False),
        sa.Column('tag_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['song_id'], ['song.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tag.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('song_id', 'tag_id')
    )
    
    # Create indexes for faster lookups
    op.create_index(op.f('ix_song_tag_song_id'), 'song_tag', ['song_id'], unique=False)
    op.create_index(op.f('ix_song_tag_tag_id'), 'song_tag', ['tag_id'], unique=False)

def downgrade():
    # Drop the indexes first
    op.drop_index(op.f('ix_song_tag_tag_id'), table_name='song_tag')
    op.drop_index(op.f('ix_song_tag_song_id'), table_name='song_tag')
    
    # Drop the tables
    op.drop_table('song_tag')
    op.drop_table('tag')

def run_migration():
    """
    Add tag and song_tag tables for the tag system if they don't exist.
    """
    import sqlite3
    import os
    import logging
    
    logger = logging.getLogger(__name__)
    logger.info("Running migration: add_tag_system")
    
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
        
        # Check if tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tag'")
        tag_table_exists = cursor.fetchone() is not None
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='song_tag'")
        song_tag_table_exists = cursor.fetchone() is not None
        
        # Create tag table if it doesn't exist
        if not tag_table_exists:
            cursor.execute('''
            CREATE TABLE tag (
                id INTEGER PRIMARY KEY,
                name VARCHAR(50) NOT NULL UNIQUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            logger.info("Created table: tag")
        else:
            logger.info("Table already exists: tag")
        
        # Create song_tag table if it doesn't exist
        if not song_tag_table_exists:
            cursor.execute('''
            CREATE TABLE song_tag (
                song_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (song_id, tag_id),
                FOREIGN KEY (song_id) REFERENCES song (id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tag (id) ON DELETE CASCADE
            )
            ''')
            logger.info("Created table: song_tag")
        else:
            logger.info("Table already exists: song_tag")
        
        # Commit changes and close connection
        conn.commit()
        conn.close()
        logger.info("Migration add_tag_system completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Migration add_tag_system failed: {str(e)}")
        return False

if __name__ == "__main__":
    # Set up logging when run directly
    import logging
    logging.basicConfig(level=logging.INFO)
    run_migration()