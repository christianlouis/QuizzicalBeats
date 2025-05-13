"""
Migration script to add Spotify audio features to the Song model
"""
import sqlite3
import os
import logging
from flask import current_app

def run_migration():
    """
    Add Spotify audio features columns to the song table if they don't exist.
    This is safe to run multiple times as it checks for column existence.
    """
    logger = logging.getLogger(__name__)
    logger.info("Running migration: add_spotify_audio_features")
    
    # Try to get the database path from Flask app config
    db_path = None
    
    # First check if we can get the path from Flask current_app
    if current_app:
        # Get the database URI from Flask's config
        db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI')
        if db_uri and db_uri.startswith('sqlite:///'):
            # Extract the path from the URI
            db_path = db_uri.replace('sqlite:///', '')
            logger.info(f"Got database path from Flask config: {db_path}")
    
    # If we couldn't get the path from Flask, try the known locations
    if not db_path or not os.path.exists(db_path):
        # Docker container path based on app configuration in __init__.py
        data_dir = '/data'
        db_path = os.path.join(data_dir, 'song_data.db')  # Path used in Flask app config
        
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
        
    try:
        # Connect to the database
        logger.info(f"Connecting to database at: {db_path}")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get existing columns
        cursor.execute("PRAGMA table_info(song)")
        columns = [column[1] for column in cursor.fetchall()]
        
        logger.info(f"Current columns in the song table: {columns}")
        
        # Define the new columns to add
        new_columns = [
            ("acousticness", "FLOAT"),
            ("danceability", "FLOAT"),
            ("energy", "FLOAT"),
            ("instrumentalness", "FLOAT"),
            ("key", "INTEGER"),
            ("liveness", "FLOAT"),
            ("loudness", "FLOAT"),
            ("mode", "INTEGER"),
            ("speechiness", "FLOAT"),
            ("tempo", "FLOAT"),
            ("time_signature", "INTEGER"),
            ("valence", "FLOAT"),
            ("duration_ms", "INTEGER"),
            ("analysis_url", "VARCHAR(500)")
        ]
        
        # Add each column if it doesn't exist
        columns_added = 0
        for column_name, column_type in new_columns:
            if column_name not in columns:
                sql = f"ALTER TABLE song ADD COLUMN {column_name} {column_type}"
                cursor.execute(sql)
                logger.info(f"Added column: {column_name} {column_type}")
                columns_added += 1
            else:
                logger.info(f"Column already exists: {column_name}")
        
        # Commit changes and close connection
        conn.commit()
        conn.close()
        
        if columns_added > 0:
            logger.info(f"Successfully added {columns_added} new columns to the database.")
        else:
            logger.info("No new columns needed to be added.")
            
        logger.info("Migration add_spotify_audio_features completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Migration add_spotify_audio_features failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

if __name__ == "__main__":
    # Set up logging when run directly
    logging.basicConfig(level=logging.INFO)
    run_migration()