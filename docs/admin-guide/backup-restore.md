# Backup and Restore

This guide explains how to back up and restore Quizzical Beats data, ensuring your music quiz system remains protected against data loss.

## Understanding Backup Components

A complete Quizzical Beats backup includes:

- **Database**: Contains all rounds, songs, user accounts, and system settings
- **Media Files**: MP3 snippets, custom intro/outro sounds, and uploaded audio
- **Configuration**: Environment variables and application settings
- **Metadata**: Version information and backup manifest

## Manual Backup Process

Perform a manual backup through the admin interface:

1. Log in as an administrator
2. Navigate to Admin > System > Backup Manager
3. Click "Create New Backup" or use the "Quick Actions" button
4. Options you can configure:
   - Custom backup name (optional)
   - Include MP3 files (enabled by default)
   - Include configuration files (enabled by default)
5. The backup will be stored in the `/data/backups` directory
6. Once completed, you can download the backup ZIP file

## Automated Backup Configuration

Set up scheduled automatic backups:

1. Go to Admin > System > Backup Manager
2. Click "Schedule Backups"
3. Configure:
   - Frequency (hourly, daily, weekly)
   - Time of execution (HH:MM format)
   - Retention policy (days to keep backups)
4. Click "Save Schedule" to apply the settings

For Docker deployments, you can configure automated backups using the Docker labels or Ofelia scheduler:

1. Click "View Configuration Suggestion" in the scheduler form
2. Choose the appropriate configuration option:
   - Docker Compose labels
   - Ofelia.ini configuration
3. Apply the suggested configuration to your Docker setup
4. Restart your containers to activate the schedule

## Backup Retention Policies

Configure how long backups are kept:

1. Navigate to Admin > System > Backup Manager
2. Click "Configure Retention"
3. Set the number of days to keep backups:
   - Enter a value between 1-365 days
   - Enter 0 to keep all backups indefinitely
4. Options:
   - Save Policy: Updates the retention settings
   - Apply Now: Immediately deletes backups older than the specified period

## Backup Management

Manage your existing backups:

1. Go to Admin > System > Backup Manager > Existing Backups
2. For each backup, you can:
   - Download: Save the backup file to your local system
   - Verify: Check the backup integrity
   - Restore: Revert your system to this backup state
   - Delete: Remove the backup file

## Restoring from Backup

Restore your system when needed:

1. Go to Admin > System > Backup Manager > Existing Backups
2. You can either:
   - Select an existing backup from the list
   - Upload a backup file using the "Upload Backup" button
3. Click the "Restore" icon next to the backup you wish to restore
4. Confirm the restore operation
5. The system will:
   - Create safety backups of your current state
   - Restore the database, MP3 files, and configuration
   - Preserve all file history

## Command-Line Backup

For scripting and automation, use the CLI commands:

```bash
# Create a backup
python run.py backup create --auto

# Apply retention policy
python run.py backup retention --days 30
```

## Backup Verification

Ensure your backups are valid:

1. Go to Admin > System > Backup Manager > Existing Backups
2. Click the "Verify" icon next to the backup
3. The system will check:
   - File integrity (ZIP structure)
   - Required files presence (database)
   - Version metadata
4. A notification will appear with the verification results

## System Health

The Backup Manager also provides a system health overview:

1. Check the "System Health" section at the bottom of the page
2. It displays the status of critical components:
   - Database connectivity
   - File storage access
   - Configuration status

## Troubleshooting Backup Issues

**Backup Failure**:
- Check storage permissions for the `/data/backups` directory
- Verify sufficient disk space
- Ensure the database is not locked by another process

**Restore Failure**:
- Ensure the backup format is compatible with your version
- Check system logs for detailed error messages
- Verify backup file integrity using the verification tool