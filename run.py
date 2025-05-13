from dotenv import load_dotenv
from musicround import create_app
from musicround.version import get_version_str, VERSION_INFO
import os
import sys
import argparse

# Load environment variables
load_dotenv()

def main():
    # Create argument parser
    parser = argparse.ArgumentParser(description='Quizzical Beats Management Script')
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Create the backup subcommand
    backup_parser = subparsers.add_parser('backup', help='Backup management')
    backup_subparsers = backup_parser.add_subparsers(dest='backup_action', help='Backup action to perform')
    
    # Create backup action
    create_parser = backup_subparsers.add_parser('create', help='Create a new backup')
    create_parser.add_argument('--auto', action='store_true', help='Create backup with automatic name')
    
    # Retention policy action
    retention_parser = backup_subparsers.add_parser('retention', help='Apply backup retention policy')
    retention_parser.add_argument('--days', type=int, default=30, help='Number of days to keep backups')
    
    # Parse the arguments
    args = parser.parse_args()
    
    # Run the command
    if args.command == 'backup':
        app = create_app()
        with app.app_context():
            if args.backup_action == 'create':
                from musicround.helpers.backup_helper import create_backup
                result = create_backup(backup_name=None if args.auto else f"manual_{VERSION_INFO['version']}")
                if result["status"] == "success":
                    print(f"Backup created successfully: {result['path']}")
                    return 0
                else:
                    print(f"Backup failed: {result['message']}")
                    return 1
            elif args.backup_action == 'retention':
                from musicround.helpers.backup_helper import apply_retention_policy
                result = apply_retention_policy(retention_days=args.days)
                if result["status"] == "success":
                    print(f"Retention policy applied: {result['message']}")
                    return 0
                else:
                    print(f"Retention policy failed: {result['message']}")
                    return 1
    else:
        # Default: Run the Flask app
        app = create_app()
        # When running in Docker, we need to listen on 0.0.0.0
        host = os.environ.get('FLASK_HOST', '0.0.0.0')
        port = int(os.environ.get('FLASK_PORT', 5000))
        
        # Enable debug mode in development
        debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
        
        # Display app version and release info
        version = get_version_str()
        print(f"Quizzical Beats {version}")
        print(f"Release Date: {VERSION_INFO['release_date']}")
        print("-" * 40)
        print(f"Starting Flask app on {host}:{port} (debug={debug})")
        app.run(host=host, port=port, debug=debug)
    
    return 0

if __name__ == '__main__':
    # Display app version and release info
    version = get_version_str()
    print(f"Quizzical Beats {version}")
    
    # Run the main function
    exit_code = main()
    sys.exit(exit_code)
