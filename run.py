from dotenv import load_dotenv
from flask import Flask
from musicround import _configure_database_uri, create_app, db
from musicround.config import Config
from musicround.version import get_version_str, VERSION_INFO
import contextlib
import json
import os
import sys
import argparse

# Load environment variables
load_dotenv()


def _create_database_cli_app():
    """Create the minimum app context needed for database CLI commands."""
    app = Flask(__name__)
    app.config.from_object(Config)
    _configure_database_uri(app)
    db.init_app(app)
    return app

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

    database_parser = subparsers.add_parser('database', help='Database diagnostics')
    database_subparsers = database_parser.add_subparsers(dest='database_action', help='Database action to perform')
    status_parser = database_subparsers.add_parser(
        'status',
        help='Print the configured database backend without credentials',
    )
    status_parser.add_argument(
        '--json',
        action='store_true',
        dest='json_output',
        help='Print machine-readable credential-safe diagnostics',
    )
    preflight_parser = database_subparsers.add_parser(
        'preflight',
        help='Validate managed database readiness without printing credentials',
    )
    preflight_parser.add_argument(
        '--allow-sqlite',
        action='store_true',
        help='Report diagnostics without failing on SQLite; useful before cutover work starts',
    )
    preflight_parser.add_argument(
        '--json',
        action='store_true',
        dest='json_output',
        help='Print machine-readable credential-safe diagnostics',
    )
    migrate_parser = database_subparsers.add_parser(
        'migrate-sqlite',
        help='Dry-run or execute a SQLite-to-configured-database row copy',
    )
    migrate_parser.add_argument(
        '--source',
        required=True,
        help='Path to the source SQLite database file, for example /data/song_data.db',
    )
    migrate_parser.add_argument(
        '--execute',
        action='store_true',
        help='Actually copy data. Omit this for the default dry run.',
    )
    migrate_parser.add_argument(
        '--replace-target',
        action='store_true',
        help='Delete existing target rows before copying. Requires --execute.',
    )
    migrate_parser.add_argument(
        '--allow-sqlite-target',
        action='store_true',
        help='Allow a SQLite target for local tests only. Production should use managed SQL.',
    )

    health_parser = subparsers.add_parser('health', help='Health diagnostics')
    health_subparsers = health_parser.add_subparsers(dest='health_action', help='Health action to perform')
    health_subparsers.add_parser('check', help='Print public-safe health status as JSON')
    
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
    elif args.command == 'database':
        if args.database_action == 'migrate-sqlite':
            if args.replace_target and not args.execute:
                print(
                    "Database migration error: --replace-target requires --execute.",
                    file=sys.stderr,
                )
                return 78
            with contextlib.redirect_stdout(sys.stderr):
                app = _create_database_cli_app()
            with app.app_context():
                from musicround.helpers.database_migration import (
                    DatabaseMigrationError,
                    migrate_sqlite_to_configured_database,
                )

                try:
                    result = migrate_sqlite_to_configured_database(
                        args.source,
                        db.engine,
                        execute=args.execute,
                        replace_target=args.replace_target,
                        allow_sqlite_target=args.allow_sqlite_target,
                    )
                except DatabaseMigrationError as exc:
                    print(f"Database migration error: {exc}", file=sys.stderr)
                    return 78
                print(json.dumps(result, indent=2, sort_keys=True))
                return 0

        from musicround.helpers.database_config import (
            database_summary,
            is_legacy_data_sqlite_uri,
            postgres_env_readiness,
        )

        app = Flask(__name__)
        app.config.from_object(Config)
        if "SQLALCHEMY_DATABASE_URI" not in os.environ:
            app.config["SQLALCHEMY_DATABASE_URI"] = None
        json_output = bool(getattr(args, "json_output", False))
        preflight_requires_managed = args.database_action == 'preflight' and not args.allow_sqlite
        if args.database_action == 'preflight':
            app.config['DATABASE_REQUIRE_MANAGED'] = preflight_requires_managed and not json_output
        try:
            _configure_database_uri(app)
        except RuntimeError as exc:
            print(f"Database configuration error: {exc}", file=sys.stderr)
            return 78
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI')
        summary = database_summary(db_uri)
        readiness = postgres_env_readiness(os.environ)
        issues = []
        if is_legacy_data_sqlite_uri(db_uri):
            issues.append(
                {
                    "code": "legacy_sqlite_data_store",
                    "severity": "warning",
                    "message": "legacy /data SQLite database is configured",
                    "hint": (
                        "configure a managed SQL URI or complete PG* credentials "
                        "via secrets for production"
                    ),
                }
            )
        diagnostics = {
            "ok": True,
            "status": "warning" if issues else "ok",
            "managed_required": preflight_requires_managed or bool(app.config.get('DATABASE_REQUIRE_MANAGED')),
            "database": summary,
            "postgres_env": readiness,
            "issues": issues,
        }
        if json_output:
            print(json.dumps(diagnostics, indent=2, sort_keys=True))
            if args.database_action == 'preflight' and issues and not args.allow_sqlite:
                return 78
            return 0
        print(f"Database backend: {summary['backend']}")
        print(f"Database target: {summary['redacted_uri']}")
        print(f"Managed database required: {bool(app.config.get('DATABASE_REQUIRE_MANAGED'))}")
        if readiness["configured"]:
            print(
                "PostgreSQL env present: "
                + ", ".join(readiness["present_required"] + readiness["present_optional"])
            )
            if readiness["missing_required"]:
                print(
                    "PostgreSQL env missing: "
                    + ", ".join(readiness["missing_required"])
                )
        if is_legacy_data_sqlite_uri(db_uri):
            print(
                "Warning: legacy /data SQLite database is configured; "
                "configure a managed SQL URI or complete PG* credentials via "
                "secrets for production."
            )
            if args.database_action == 'preflight' and not args.allow_sqlite:
                print(
                    "Preflight failed: managed database cutover is not ready "
                    "while legacy SQLite is configured.",
                    file=sys.stderr,
                )
                return 78
        if args.database_action == 'preflight':
            print("Database preflight passed.")
        return 0
    elif args.command == 'health':
        with contextlib.redirect_stdout(sys.stderr):
            app = create_app()
        with app.app_context():
            from musicround.helpers.service_health import application_health_payload

            payload = application_health_payload()
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0 if payload["ok"] else 1
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
    # Run the main function
    exit_code = main()
    sys.exit(exit_code)
