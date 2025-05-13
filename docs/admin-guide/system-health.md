# System Health Monitoring

This guide explains how to monitor, troubleshoot, and maintain the health of your Quizzical Beats installation.

## Health Dashboard

Quizzical Beats provides a built-in health dashboard that gives you a comprehensive overview of your system:

1. Log in as an administrator
2. Navigate to Admin > System > Health Dashboard
3. The dashboard displays:
   - Database information (status, song count, round count, user count)
   - Storage information (directory status, file counts, sizes)
   - External service status
   - Memory usage
   - Version information

### Health Status Cards

The top of the health dashboard features status cards that provide a quick overview of your system's health:

- **Database**: Connection status and database health
- **Storage**: File storage status and access permissions
- **API Services**: Status of external API connections
- **Memory**: System memory availability and usage

Each card is color-coded to indicate status:
- Green: Good/healthy
- Yellow: Warning/potential issues
- Red: Error/critical issues

## Database Monitoring

### Database Statistics

The database section of the health dashboard shows:

- Total number of songs in the database
- Total number of rounds
- Total number of users
- Database file size
- Last backup timestamp

This information helps you track database growth and ensure you're performing regular backups.

## Storage Monitoring

The storage section provides information about key directories:

- Directory name
- Number of files in each directory
- Total size of files
- Write permission status

This helps you identify potential storage issues such as:
- Lack of write permissions
- Unexpected growth in file count or size
- Directories approaching storage limits

## External Service Monitoring

The External Services section displays the status of integrated third-party services:

- Service name
- Connection status (Available, Warning, Unavailable)
- Status details or error messages

Services monitored may include:
- Spotify API
- Dropbox API
- OpenAI API
- Email service
- Other integrated services based on your configuration

## Version Information

The Version Information section shows:

- Application version
- Release name
- Release date
- Python version
- Operating system platform
- Flask version

This information is essential when troubleshooting issues or planning updates.

## Troubleshooting Common Issues

### Database Connection Issues

If the database status shows errors:

1. Check database credentials in your `.env` file
2. Verify that the database file exists at the configured location
3. Check file permissions on the database file
4. Ensure there's enough disk space for database growth

### Storage Issues

If the Storage status shows problems:

1. Check directory permissions for the affected directories
2. Verify that the application has write access to these directories
3. Ensure sufficient disk space is available
4. Check for file corruption or missing critical files

### External Service Connectivity

If service connections are failing:

1. Verify API keys and credentials in your `.env` file
2. Check that redirect URIs are correctly configured
3. Test external connectivity to the service endpoints
4. Verify SSL certificates are valid for secure connections
5. Check for API rate limiting or service outages

## CLI Health Checks

For command-line health checks, you can use:

```bash
python run.py health check
```

This command performs basic health checks and outputs the results to the console, which is useful for automated monitoring scripts.

## Best Practices for System Health

1. **Regular Monitoring**: Check the health dashboard at least weekly
2. **Automated Alerts**: Set up external monitoring for critical services
3. **Preventive Maintenance**: Address warning signs before they become critical
4. **Regular Backups**: Configure automated backups and verify them regularly
5. **Update Management**: Keep the application and dependencies up to date
6. **Resource Planning**: Monitor growth trends to plan for future resource needs

## Related Documentation

- [Backup and Restore](backup-restore.md) - For information on configuring backups
- [Configuration Guide](configuration.md) - For details on configuring external services
- [Installation Guide](installation.md) - For system requirements and setup