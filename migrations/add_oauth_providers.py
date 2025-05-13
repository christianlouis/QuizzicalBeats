"""
Migration script to add Google and Authentik OAuth fields to the User table
"""
from datetime import datetime
import logging
from sqlalchemy import text, inspect

logger = logging.getLogger(__name__)

def run_migration():
    """
    Add new columns to the User table for Google and Authentik OAuth integration
    Returns:
    - True: if changes were made successfully
    - None: if no changes were needed (already up to date)
    - False: if errors occurred
    """
    from musicround import db
    
    # Track changes made
    changes_made = False
    
    try:
        # Connect to the database
        inspector = inspect(db.engine)
        existing_columns = [column['name'] for column in inspector.get_columns('user')]
        
        # Use connection for executing SQL statements
        with db.engine.connect() as conn:
            # Add auth_provider column if it doesn't exist
            if 'auth_provider' not in existing_columns:
                logger.info("Adding auth_provider column")
                try:
                    conn.execute(text('ALTER TABLE user ADD COLUMN auth_provider VARCHAR(20)'))
                    # Set default value for existing rows
                    conn.execute(text("UPDATE user SET auth_provider = 'local' WHERE auth_provider IS NULL"))
                    conn.commit()
                    changes_made = True
                    logger.info("Added auth_provider column")
                except Exception as e:
                    logger.error(f"Error adding auth_provider column: {str(e)}")
            
            # Add Google OAuth columns
            if 'google_id' not in existing_columns:
                logger.info("Adding google_id column")
                try:
                    conn.execute(text('ALTER TABLE user ADD COLUMN google_id VARCHAR(100)'))
                    conn.commit()
                    changes_made = True
                    logger.info("Added google_id column")
                except Exception as e:
                    logger.error(f"Error adding google_id column: {str(e)}")
                
            if 'google_token' not in existing_columns:
                logger.info("Adding google_token column")
                try:
                    conn.execute(text('ALTER TABLE user ADD COLUMN google_token TEXT'))
                    conn.commit()
                    changes_made = True
                    logger.info("Added google_token column")
                except Exception as e:
                    logger.error(f"Error adding google_token column: {str(e)}")
                
            if 'google_refresh_token' not in existing_columns:
                logger.info("Adding google_refresh_token column")
                try:
                    conn.execute(text('ALTER TABLE user ADD COLUMN google_refresh_token TEXT'))
                    conn.commit()
                    changes_made = True
                    logger.info("Added google_refresh_token column")
                except Exception as e:
                    logger.error(f"Error adding google_refresh_token column: {str(e)}")
            
            # Add Authentik OAuth columns
            if 'authentik_id' not in existing_columns:
                logger.info("Adding authentik_id column")
                try:
                    conn.execute(text('ALTER TABLE user ADD COLUMN authentik_id VARCHAR(100)'))
                    conn.commit()
                    changes_made = True
                    logger.info("Added authentik_id column")
                except Exception as e:
                    logger.error(f"Error adding authentik_id column: {str(e)}")
                
            if 'authentik_token' not in existing_columns:
                logger.info("Adding authentik_token column")
                try:
                    conn.execute(text('ALTER TABLE user ADD COLUMN authentik_token TEXT'))
                    conn.commit()
                    changes_made = True
                    logger.info("Added authentik_token column")
                except Exception as e:
                    logger.error(f"Error adding authentik_token column: {str(e)}")
                
            if 'authentik_refresh_token' not in existing_columns:
                logger.info("Adding authentik_refresh_token column")
                try:
                    conn.execute(text('ALTER TABLE user ADD COLUMN authentik_refresh_token TEXT'))
                    conn.commit()
                    changes_made = True
                    logger.info("Added authentik_refresh_token column")
                except Exception as e:
                    logger.error(f"Error adding authentik_refresh_token column: {str(e)}")
            
            # Make password_hash nullable for OAuth-only users
            try:
                # Due to SQLite limitations, we need to recreate the table to change column nullability
                # Check if it's already nullable
                is_nullable = False
                result = conn.execute(text("PRAGMA table_info('user')"))
                columns_info = result.fetchall()
                
                for col in columns_info:
                    if col[1] == 'password_hash' and col[3] == 0:  # 0 means nullable
                        is_nullable = True
                        break

                if not is_nullable:
                    logger.info("Modifying password_hash to be nullable")
                    # Get all column definitions
                    columns = []
                    for col_info in columns_info:
                        name = col_info[1]
                        type_name = col_info[2]
                        not_null = "NOT NULL" if col_info[3] == 1 and name != "password_hash" else ""
                        pk = "PRIMARY KEY" if col_info[5] == 1 else ""
                        columns.append(f"{name} {type_name} {pk} {not_null}".strip())
                    
                    # Create a temporary table with the new schema
                    column_defs = ", ".join(columns)
                    conn.execute(text(f'CREATE TABLE user_temp ({column_defs})'))
                    
                    # Copy data from the old table
                    conn.execute(text('INSERT INTO user_temp SELECT * FROM user'))
                    
                    # Replace the old table
                    conn.execute(text('DROP TABLE user'))
                    conn.execute(text('ALTER TABLE user_temp RENAME TO user'))
                    conn.commit()
                    
                    changes_made = True
                    logger.info("Made password_hash column nullable for OAuth-only users")
                else:
                    logger.info("password_hash is already nullable")
            except Exception as e:
                logger.error(f"Error modifying password_hash column: {str(e)}")
        
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