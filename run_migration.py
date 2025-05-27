"""
Manually run the OAuth providers migration script
"""
import os
import sys
from flask import Flask
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add the parent directory to the path so we can import modules
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Ensure the project root is also in the path for musicround imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '.'))  # Assuming run_migration.py is in project root
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def run_spotify_oauth_migration():
    """Run the migration to add Spotify OAuth columns"""
    try:
        # Create a minimal Flask app with database connection
        from musicround import db, create_app
        app = create_app()
        
        with app.app_context():
            logger.info("Starting Spotify OAuth columns migration...")
            
            # Import and run the migration script
            from migrations.add_spotify_oauth_columns import run_migration
            success = run_migration()
            
            if success:
                logger.info("Migration completed successfully!")
                return True
            else:
                logger.info("Migration reported no changes needed - continuing anyway")
                return True  # Return True even when no changes were made
                
    except Exception as e:
        logger.error(f"Error running migration: {str(e)}")
        return False

if __name__ == "__main__":
    success = run_spotify_oauth_migration()
    sys.exit(0 if success else 1)  # Exit with 0 (success) or 1 (error)