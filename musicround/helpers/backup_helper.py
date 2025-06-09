"""
Backup helper functions for creating, managing, and restoring backups.
"""
import os
import shutil
import json
import logging
import sqlite3
import zipfile
from datetime import datetime
import tempfile
from flask import current_app

# Set up logging
logger = logging.getLogger(__name__)

def create_backup(backup_name=None, include_mp3s=True, include_config=True):
    """
    Create a full system backup including database, MP3s, and configuration.
    
    Args:
        backup_name: Optional name for the backup (defaults to timestamp)
        include_mp3s: Whether to include MP3 files in the backup
        include_config: Whether to include configuration files
        
    Returns:
        dict: Backup information including path and status
    """
    try:
        # Generate backup name if not provided
        if not backup_name:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_name = f"backup_{timestamp}"
        
        # Ensure backup directory exists
        backup_dir = os.path.join('/data', 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        # Create backup zip file path
        backup_path = os.path.join(backup_dir, f"{backup_name}.zip")
        
        # Create a temporary directory for collecting files
        with tempfile.TemporaryDirectory() as temp_dir:
            # Step 1: Backup the database
            db_path = current_app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
            
            if os.path.exists(db_path):
                # Create a copy of the database (to avoid locking issues)
                temp_db = os.path.join(temp_dir, 'song_data.db')
                
                # Connect to source database and back it up
                conn = sqlite3.connect(db_path)
                backup_conn = sqlite3.connect(temp_db)
                conn.backup(backup_conn)
                conn.close()
                backup_conn.close()
                
                logger.info(f"Database backed up to {temp_db}")
            else:
                logger.error(f"Database not found at {db_path}")
                return {
                    "status": "error",
                    "message": f"Database not found at {db_path}",
                    "path": None
                }
            
            # Step 2: Copy MP3 files if requested
            if include_mp3s:
                mp3_dir = os.path.join(os.path.dirname(current_app.root_path), 'mp3')
                if os.path.exists(mp3_dir):
                    mp3_backup_dir = os.path.join(temp_dir, 'mp3')
                    os.makedirs(mp3_backup_dir, exist_ok=True)
                    
                    # Copy all MP3 files
                    for mp3_file in os.listdir(mp3_dir):
                        if mp3_file.endswith('.mp3'):
                            source_path = os.path.join(mp3_dir, mp3_file)
                            dest_path = os.path.join(mp3_backup_dir, mp3_file)
                            shutil.copy2(source_path, dest_path)
                    
                    logger.info(f"MP3 files backed up to {mp3_backup_dir}")
                else:
                    logger.warning(f"MP3 directory not found at {mp3_dir}")
            
            # Step 3: Add configuration files if requested
            if include_config:
                config_dir = os.path.join(temp_dir, 'config')
                os.makedirs(config_dir, exist_ok=True)
                
                # Copy .env file if it exists
                env_path = os.path.join(os.path.dirname(current_app.root_path), '.env')
                if os.path.exists(env_path):
                    shutil.copy2(env_path, os.path.join(config_dir, '.env'))
                    logger.info(f".env file backed up")
                
                # Extract system settings from database and save as JSON
                try:
                    from musicround.models import SystemSetting
                    settings = SystemSetting.all_settings()
                    
                    # Save settings to JSON file
                    settings_path = os.path.join(config_dir, 'system_settings.json')
                    with open(settings_path, 'w') as f:
                        json.dump(settings, f, indent=2)
                    
                    logger.info(f"System settings backed up to {settings_path}")
                except Exception as e:
                    logger.error(f"Error backing up system settings: {str(e)}")
            
            # Step 4: Add backup metadata file with version info and timestamp
            from musicround.version import VERSION_INFO
            
            metadata = {
                "backup_name": backup_name,
                "timestamp": datetime.now().isoformat(),
                "version": VERSION_INFO['version'],
                "release_name": VERSION_INFO['release_name'],
                "includes_mp3s": include_mp3s,
                "includes_config": include_config
            }
            
            metadata_path = os.path.join(temp_dir, 'backup_metadata.json')
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            # Step 5: Create a ZIP archive of all backed up content
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Add all files from temp directory to ZIP
                for root, _, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # Add file to ZIP with a relative path
                        arcname = os.path.relpath(file_path, temp_dir)
                        zipf.write(file_path, arcname)
        
        # Get backup file size
        backup_size = os.path.getsize(backup_path)
        
        return {
            "status": "success",
            "message": "Backup created successfully",
            "path": backup_path,
            "name": backup_name,
            "size": backup_size,
            "timestamp": datetime.now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error during backup creation: {str(e)}")
        return {
            "status": "error",
            "message": f"Backup failed: {str(e)}",
            "path": None
        }

def list_backups():
    """
    List all available backups with their metadata.
    
    Returns:
        list: List of backup information dictionaries
    """
    backup_dir = os.path.join('/data', 'backups')
    
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir, exist_ok=True)
        return []
    
    backups = []
    
    for filename in os.listdir(backup_dir):
        if filename.endswith('.zip'):
            backup_path = os.path.join(backup_dir, filename)
            try:
                # Extract metadata from ZIP file
                with zipfile.ZipFile(backup_path, 'r') as zipf:
                    if 'backup_metadata.json' in zipf.namelist():
                        with zipf.open('backup_metadata.json') as f:
                            metadata = json.load(f)
                            
                            # Add file information to metadata
                            file_info = os.stat(backup_path)
                            metadata['file_size'] = file_info.st_size
                            metadata['file_name'] = filename
                            metadata['file_path'] = backup_path
                            metadata['file_date'] = datetime.fromtimestamp(file_info.st_mtime).isoformat()
                            
                            backups.append(metadata)
                    else:
                        # No metadata file, create basic info
                        file_info = os.stat(backup_path)
                        backups.append({
                            'backup_name': os.path.splitext(filename)[0],
                            'file_name': filename,
                            'file_path': backup_path,
                            'file_size': file_info.st_size,
                            'file_date': datetime.fromtimestamp(file_info.st_mtime).isoformat(),
                            'timestamp': datetime.fromtimestamp(file_info.st_mtime).isoformat(),
                            'version': 'Unknown',
                            'release_name': 'Unknown'
                        })
            except Exception as e:
                logger.error(f"Error reading backup metadata from {filename}: {str(e)}")
    
    # Sort backups by timestamp (newest first)
    backups.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    return backups

def delete_backup(backup_filename):
    """
    Delete a backup file.
    
    Args:
        backup_filename: Name of the backup file to delete
        
    Returns:
        dict: Operation status information
    """
    backup_dir = os.path.join('/data', 'backups')
    backup_path = os.path.join(backup_dir, backup_filename)
    
    if not os.path.exists(backup_path):
        return {
            "status": "error",
            "message": f"Backup file {backup_filename} not found"
        }
    
    try:
        os.remove(backup_path)
        return {
            "status": "success",
            "message": f"Backup {backup_filename} deleted successfully"
        }
    except Exception as e:
        logger.error(f"Error deleting backup {backup_filename}: {str(e)}")
        return {
            "status": "error",
            "message": f"Error deleting backup: {str(e)}"
        }

def restore_backup(backup_filename):
    """
    Restore system from a backup file.
    
    Args:
        backup_filename: Name of the backup file to restore
        
    Returns:
        dict: Operation status information
    """
    backup_dir = os.path.join('/data', 'backups')
    backup_path = os.path.join(backup_dir, backup_filename)
    
    if not os.path.exists(backup_path):
        return {
            "status": "error",
            "message": f"Backup file {backup_filename} not found"
        }
    
    try:
        # Create a temporary directory for extracting backup
        with tempfile.TemporaryDirectory() as temp_dir:
            # Extract the backup ZIP
            with zipfile.ZipFile(backup_path, 'r') as zipf:
                zipf.extractall(temp_dir)
            
            # Get backup metadata
            metadata_path = os.path.join(temp_dir, 'backup_metadata.json')
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
            else:
                metadata = {
                    "includes_mp3s": True,
                    "includes_config": True
                }
            
            # Restore database
            db_backup_path = os.path.join(temp_dir, 'song_data.db')
            db_path = current_app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
            
            if os.path.exists(db_backup_path):
                # Create a backup of the current database before overwriting
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                db_current_backup = f"{db_path}.{timestamp}.bak"
                
                if os.path.exists(db_path):
                    shutil.copy2(db_path, db_current_backup)
                    logger.info(f"Created backup of current database at {db_current_backup}")
                
                # Restore the database from backup
                shutil.copy2(db_backup_path, db_path)
                logger.info(f"Restored database from backup")
            else:
                logger.error("Database file not found in backup")
                return {
                    "status": "error",
                    "message": "Database file not found in backup"
                }
            
            # Restore MP3 files if included in backup
            if metadata.get("includes_mp3s", True):
                mp3_backup_dir = os.path.join(temp_dir, 'mp3')
                if os.path.exists(mp3_backup_dir):
                    mp3_dir = os.path.join(os.path.dirname(current_app.root_path), 'mp3')
                    
                    # Create backup of current MP3 files
                    if os.path.exists(mp3_dir):
                        mp3_backup = f"{mp3_dir}.{timestamp}.bak"
                        shutil.copytree(mp3_dir, mp3_backup)
                        logger.info(f"Created backup of current MP3 files at {mp3_backup}")
                    
                    # Remove current MP3 directory and replace with backup
                    if os.path.exists(mp3_dir):
                        shutil.rmtree(mp3_dir)
                    
                    # Create MP3 directory if it doesn't exist
                    os.makedirs(mp3_dir, exist_ok=True)
                    
                    # Copy MP3 files from backup
                    for mp3_file in os.listdir(mp3_backup_dir):
                        if mp3_file.endswith('.mp3'):
                            source_path = os.path.join(mp3_backup_dir, mp3_file)
                            dest_path = os.path.join(mp3_dir, mp3_file)
                            shutil.copy2(source_path, dest_path)
                    
                    logger.info(f"Restored MP3 files from backup")
            
            # Restore config files if included in backup
            if metadata.get("includes_config", True):
                config_backup_dir = os.path.join(temp_dir, 'config')
                if os.path.exists(config_backup_dir):
                    # Restore .env file if present in backup
                    env_backup_path = os.path.join(config_backup_dir, '.env')
                    if os.path.exists(env_backup_path):
                        env_path = os.path.join(os.path.dirname(current_app.root_path), '.env')
                        
                        # Backup current .env
                        if os.path.exists(env_path):
                            env_backup = f"{env_path}.{timestamp}.bak"
                            shutil.copy2(env_path, env_backup)
                            logger.info(f"Created backup of current .env file at {env_backup}")
                        
                        # Restore .env from backup
                        shutil.copy2(env_backup_path, env_path)
                        logger.info(f"Restored .env file from backup")
                    
                    # Restore system settings from JSON if present
                    settings_backup_path = os.path.join(config_backup_dir, 'system_settings.json')
                    if os.path.exists(settings_backup_path):
                        try:
                            with open(settings_backup_path, 'r') as f:
                                settings = json.load(f)
                            
                            # Import within function to avoid circular imports
                            from musicround.models import SystemSetting, db
                            
                            # Restore each setting
                            for key, value in settings.items():
                                SystemSetting.set(key, value)
                            
                            logger.info("Restored system settings from backup")
                        except Exception as e:
                            logger.error(f"Error restoring system settings: {str(e)}")
        
        return {
            "status": "success",
            "message": "Backup restored successfully",
            "backup_name": backup_filename
        }
    
    except Exception as e:
        logger.error(f"Error restoring backup {backup_filename}: {str(e)}")
        return {
            "status": "error",
            "message": f"Error restoring backup: {str(e)}"
        }

def verify_backup(backup_filename):
    """
    Verify the integrity of a backup file.
    
    Args:
        backup_filename: Name of the backup file to verify
        
    Returns:
        dict: Verification result
    """
    backup_dir = os.path.join('/data', 'backups')
    backup_path = os.path.join(backup_dir, backup_filename)
    
    if not os.path.exists(backup_path):
        return {
            "status": "error",
            "message": f"Backup file {backup_filename} not found",
            "is_valid": False
        }
    
    try:
        # Check if the file is a valid ZIP
        if not zipfile.is_zipfile(backup_path):
            return {
                "status": "error",
                "message": f"Backup file is not a valid ZIP archive",
                "is_valid": False
            }
        
        # Try to open the ZIP and extract metadata
        with zipfile.ZipFile(backup_path, 'r') as zipf:
            # Test the integrity of all files in the ZIP
            test_result = zipf.testzip()
            if test_result is not None:
                return {
                    "status": "error",
                    "message": f"Backup file contains corrupted files, first bad file: {test_result}",
                    "is_valid": False
                }
            
            # Check for essential files
            if 'song_data.db' not in zipf.namelist():
                return {
                    "status": "error",
                    "message": "Backup file does not contain a database",
                    "is_valid": False
                }
            
            # Extract metadata if available
            if 'backup_metadata.json' in zipf.namelist():
                with zipf.open('backup_metadata.json') as f:
                    metadata = json.load(f)
            else:
                metadata = {"version": "Unknown"}
        
        # If we got here, the backup is valid
        return {
            "status": "success",
            "message": "Backup file is valid",
            "is_valid": True,
            "version": metadata.get("version", "Unknown"),
            "timestamp": metadata.get("timestamp", "Unknown")
        }
    
    except Exception as e:
        logger.error(f"Error verifying backup {backup_filename}: {str(e)}")
        return {
            "status": "error",
            "message": f"Error verifying backup: {str(e)}",
            "is_valid": False
        }

def schedule_backup(schedule_time=None, frequency='daily', retention_days=30):
    """
    Schedule automatic backups.
    
    Args:
        schedule_time: Time to run the backup (HH:MM format)
        frequency: Frequency of backups ('hourly', 'daily', 'weekly')
        retention_days: Number of days of backups to keep (0 = keep all)
        
    Returns:
        dict: Operation status information
    """
    # This would typically integrate with a scheduler like cron
    # For now, we'll just store the settings in SystemSetting
    try:
        from musicround.models import SystemSetting
        
        # Get current time if not provided
        if schedule_time is None:
            schedule_time = datetime.now().strftime('%H:%M')
        
        # Store backup schedule settings
        SystemSetting.set('backup_schedule_time', schedule_time)
        SystemSetting.set('backup_schedule_frequency', frequency)
        SystemSetting.set('backup_schedule_enabled', 'true')
        SystemSetting.set('backup_retention_days', str(retention_days))
        
        # If retention policy is set, apply it immediately
        if retention_days > 0:
            apply_retention_policy(retention_days)
        
        return {
            "status": "success",
            "message": f"Backup scheduled for {schedule_time} ({frequency}), keeping {retention_days} days of backups",
            "schedule_time": schedule_time,
            "frequency": frequency,
            "retention_days": retention_days
        }
    except Exception as e:
        logger.error(f"Error scheduling backup: {str(e)}")
        return {
            "status": "error",
            "message": f"Error scheduling backup: {str(e)}"
        }

def get_backup_summary():
    """
    Get a summary of backup system status.
    
    Returns:
        dict: Summary information including counts, schedule info, etc.
    """
    from musicround.models import SystemSetting
    
    # Get all backups
    backups = list_backups()
    
    # Extract info from settings
    schedule_enabled = SystemSetting.get('backup_schedule_enabled', 'false') == 'true'
    schedule_time = SystemSetting.get('backup_schedule_time', '03:00')
    schedule_frequency = SystemSetting.get('backup_schedule_frequency', 'daily')
    retention_days = int(SystemSetting.get('backup_retention_days', '30'))
    
    # Calculate next backup time based on schedule
    from datetime import datetime, time, timedelta
    now = datetime.now()
    
    next_backup = None
    if schedule_enabled:
        try:
            # Parse schedule time
            hour, minute = map(int, schedule_time.split(':'))
            schedule_time_obj = time(hour, minute)
            
            # Calculate next occurrence
            next_backup_date = now.date()
            next_backup_datetime = datetime.combine(next_backup_date, schedule_time_obj)
            
            # If today's scheduled time has passed, move to next occurrence based on frequency
            if next_backup_datetime < now:
                if schedule_frequency == 'hourly':
                    next_backup_datetime = now + timedelta(hours=1)
                elif schedule_frequency == 'daily':
                    next_backup_datetime = datetime.combine(next_backup_date + timedelta(days=1), schedule_time_obj)
                elif schedule_frequency == 'weekly':
                    next_backup_datetime = datetime.combine(next_backup_date + timedelta(days=7), schedule_time_obj)
                    
            next_backup = next_backup_datetime.strftime('%Y-%m-%d %H:%M')
        except:
            next_backup = "Error calculating next backup time"
    
    # Get latest backup info
    latest_backup = backups[0] if backups else None
    
    return {
        "backup_count": len(backups),
        "latest_backup": latest_backup,
        "schedule_enabled": schedule_enabled,
        "schedule_time": schedule_time,
        "schedule_frequency": schedule_frequency,
        "next_backup": next_backup,
        "backup_location": "/data/backups",
        "retention_days": retention_days
    }

def generate_backup_config_suggestion(retention_days=30):
    """
    Generate a configuration suggestion for setting up automated backups.
    This does NOT modify any files, it only returns a suggestion.
    
    Args:
        retention_days: Number of days to keep backups
        
    Returns:
        dict: Configuration suggestion and instructions
    """
    # Generate the backup schedule configuration suggestion
    from musicround.models import SystemSetting
    
    # Get backup schedule information
    schedule_time = SystemSetting.get('backup_schedule_time', '03:00')
    schedule_frequency = SystemSetting.get('backup_schedule_frequency', 'daily')
    
    # Map schedule frequency to cron expressions for documentation
    frequency_map = {
        'hourly': '@hourly',
        'daily': '@daily',
        'weekly': '@weekly'
    }
    
    schedule_cron = frequency_map.get(schedule_frequency, '@daily')
    
    # Generate docker-compose config example
    docker_compose_suggestion = f"""labels:
  ofelia.enabled: "true"
  ofelia.job-exec.backup.schedule: "{schedule_cron}"
  ofelia.job-exec.backup.command: "python /app/run.py backup create --auto"
  ofelia.job-exec.backup.no-overlap: "true"
  # Retention policy - automatically delete backups older than {retention_days} days
  ofelia.job-exec.retention.schedule: "@weekly"
  ofelia.job-exec.retention.command: "python /app/run.py backup retention --days {retention_days}"
  ofelia.job-exec.retention.no-overlap: "true"
"""

    # Generate ofelia.ini config example (for standalone setups)
    ofelia_ini_suggestion = f"""[global]
save-folder = /var/log/ofelia

[job-exec "backup"]
schedule = {schedule_cron}
command = python /app/run.py backup create --auto
user = root
no-overlap = true

[job-exec "retention"]
schedule = @weekly
command = python /app/run.py backup retention --days {retention_days}
user = root
no-overlap = true
"""

    # Generate instructions for manual setup
    instructions = f"""To set up automated backups, add the configuration to your Docker Compose file OR use the ofelia.ini file.

Option 1: Add these labels to your main service in docker-compose.yml:
{docker_compose_suggestion}

Option 2: Add these sections to ofelia.ini:
{ofelia_ini_suggestion}

After making changes, restart your containers to apply the configuration:
docker-compose down
docker-compose up -d
"""

    return {
        "status": "success",
        "schedule": {
            "frequency": schedule_frequency,
            "time": schedule_time,
            "retention_days": retention_days
        },
        "docker_compose_suggestion": docker_compose_suggestion,
        "ofelia_ini_suggestion": ofelia_ini_suggestion,
        "instructions": instructions,
        "message": "Generated backup configuration suggestion"
    }

def apply_retention_policy(retention_days=30):
    """
    Apply the backup retention policy by deleting old backups.
    
    Args:
        retention_days: Number of days of backups to keep (0 = keep all)
        
    Returns:
        dict: Operation status information
    """
    if retention_days <= 0:
        return {
            "status": "success",
            "message": "Retention policy disabled, all backups kept",
            "deleted_count": 0,
            "deleted_backups": []
        }
    
    try:
        from datetime import datetime, timedelta
        import os
        
        # Get the cutoff date
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        
        # Get list of all backups
        backups = list_backups()
        
        # Filter to find backups older than the cutoff date
        deleted_backups = []
        
        for backup in backups:
            # Get backup timestamp
            backup_time = None
            
            if 'timestamp' in backup:
                try:
                    backup_time = datetime.fromisoformat(backup['timestamp'])
                except (ValueError, TypeError):
                    # Try the file date as fallback
                    if 'file_date' in backup:
                        try:
                            backup_time = datetime.fromisoformat(backup['file_date'])
                        except (ValueError, TypeError):
                            # Can't determine date, skip this backup
                            continue
            elif 'file_date' in backup:
                try:
                    backup_time = datetime.fromisoformat(backup['file_date'])
                except (ValueError, TypeError):
                    # Can't determine date, skip this backup
                    continue
            
            # If we couldn't determine when this backup was created, skip it
            if not backup_time:
                continue
            
            # Check if this backup is older than the cutoff date
            if backup_time < cutoff_date:
                backup_path = backup.get('file_path')
                if backup_path and os.path.exists(backup_path):
                    try:
                        os.remove(backup_path)
                        deleted_backups.append({
                            'name': backup.get('backup_name') or os.path.basename(backup_path),
                            'date': backup_time.isoformat()
                        })
                    except Exception as e:
                        logger.error(f"Error deleting old backup {backup_path}: {str(e)}")
        
        return {
            "status": "success",
            "message": f"Retention policy applied: deleted {len(deleted_backups)} backups older than {retention_days} days",
            "deleted_count": len(deleted_backups),
            "deleted_backups": deleted_backups
        }
    
    except Exception as e:
        logger.error(f"Error applying retention policy: {str(e)}")
        return {
            "status": "error",
            "message": f"Error applying retention policy: {str(e)}",
            "deleted_count": 0,
            "deleted_backups": []
        }

def upload_backup(file):
    """
    Upload and validate a backup file to the system
    
    Args:
        file: A FileStorage object from Flask's request.files
        
    Returns:
        dict: Operation status and information about the uploaded backup
    """
    try:
        # Ensure backup directory exists
        backup_dir = os.path.join('/data', 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        # Generate a unique filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Save the file with original filename but prefixed with timestamp
        # This preserves the original filename but ensures uniqueness
        secure_filename = file.filename.replace(' ', '_')
        save_filename = f"{timestamp}_{secure_filename}"
        save_path = os.path.join(backup_dir, save_filename)
        
        # Save the uploaded file
        file.save(save_path)
        logger.info(f"Uploaded backup saved to {save_path}")
        
        # Validate the backup file - check if it's a valid zip file
        if not zipfile.is_zipfile(save_path):
            # Clean up invalid file
            if os.path.exists(save_path):
                os.remove(save_path)
            return {
                "status": "error",
                "message": "Uploaded file is not a valid backup archive."
            }
        
        # Basic validation of backup contents
        with zipfile.ZipFile(save_path, 'r') as zip_ref:
            file_list = zip_ref.namelist()
            # Check for essential files in the backup
            if 'database.db' not in file_list and 'song_data.db' not in file_list:
                # Clean up invalid backup
                if os.path.exists(save_path):
                    os.remove(save_path)
                return {
                    "status": "error",
                    "message": "Uploaded file is not a valid Quizzical Beats backup. No database found."
                }
        
        # Return success with file info
        file_size = os.path.getsize(save_path)
        readable_size = f"{file_size / (1024*1024):.2f} MB"
        
        return {
            "status": "success",
            "message": f"Backup uploaded successfully ({readable_size}).",
            "filename": save_filename,
            "path": save_path,
            "size": file_size,
            "upload_time": timestamp
        }
        
    except Exception as e:
        logger.error(f"Error uploading backup: {str(e)}")
        return {
            "status": "error",
            "message": f"Error uploading backup: {str(e)}"
        }

def update_ofelia_config(retention_days=30):
    """
    Update the Ofelia scheduler configuration file based on current backup settings.
    This creates or updates the config file that Ofelia uses for scheduling backups.
    
    Args:
        retention_days: Number of days of backups to keep (0 = keep all)
        
    Returns:
        dict: Operation status information and config details
    """
    try:
        from musicround.models import SystemSetting
        import os
        
        # Get backup schedule information
        schedule_time = SystemSetting.get('backup_schedule_time', '03:00')
        schedule_frequency = SystemSetting.get('backup_schedule_frequency', 'daily')
        schedule_enabled = SystemSetting.get('backup_schedule_enabled', 'true') == 'true'
        
        # Map schedule frequency to cron expressions
        frequency_map = {
            'hourly': '@hourly',
            'daily': '@daily', 
            'weekly': '@weekly'
        }
        
        schedule_cron = frequency_map.get(schedule_frequency, '@daily')
        
        # Determine the config file path - use environment variable or default
        config_dir = os.environ.get('OFELIA_CONFIG_DIR', '/data/config')
        os.makedirs(config_dir, exist_ok=True)
        config_path = os.path.join(config_dir, 'ofelia.ini')
        
        # Create the config content
        config_content = f"""[global]
save-folder = /var/log/ofelia

[job-exec "backup"]
schedule = {schedule_cron}
command = python /app/run.py backup create --auto
user = root
no-overlap = true

[job-exec "retention"]
schedule = @weekly
command = python /app/run.py backup retention --days {retention_days}
user = root
no-overlap = true
"""

        # If backup scheduling is disabled, add a comment at the top
        if not schedule_enabled:
            config_content = "# AUTOMATED BACKUPS DISABLED - Enable in system settings\n# Remove this comment to enable this configuration\n\n" + config_content
        
        # Write the config file
        with open(config_path, 'w') as f:
            f.write(config_content)
        
        logger.info(f"Updated Ofelia configuration at {config_path}")
        
        # Also generate a docker-compose labels suggestion for documentation
        docker_compose_suggestion = f"""labels:
  ofelia.enabled: "true"
  ofelia.job-exec.backup.schedule: "{schedule_cron}"
  ofelia.job-exec.backup.command: "python /app/run.py backup create --auto"
  ofelia.job-exec.backup.no-overlap: "true"
  # Retention policy - automatically delete backups older than {retention_days} days
  ofelia.job-exec.retention.schedule: "@weekly"
  ofelia.job-exec.retention.command: "python /app/run.py backup retention --days {retention_days}"
  ofelia.job-exec.retention.no-overlap: "true"
"""
        
        # Generate instructions 
        instructions = f"""To use this Ofelia configuration:

1. Make sure the ofelia.ini file is accessible to the Ofelia scheduler
2. If using Docker Compose with the Ofelia sidecar pattern, update your docker-compose.yml file
   with the labels shown below
3. Restart the application for changes to take effect

For containerized setups:
docker-compose down
docker-compose up -d
"""
        
        return {
            "status": "success",
            "message": f"Updated Ofelia configuration at {config_path}",
            "config_path": config_path,
            "config_content": config_content,
            "docker_labels": docker_compose_suggestion,
            "instructions": instructions,
            "schedule": {
                "enabled": schedule_enabled,
                "frequency": schedule_frequency,
                "time": schedule_time,
                "retention_days": retention_days
            }
        }
        
    except Exception as e:
        logger.error(f"Error updating Ofelia configuration: {str(e)}")
        return {
            "status": "error",
            "message": f"Failed to update Ofelia configuration: {str(e)}",
            "config_path": None,
            "config_content": None
        }