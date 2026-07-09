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


def _create_backup_readiness_cli_app():
    """Create a minimal app for backup diagnostics without DB side effects."""
    app = Flask(__name__)
    app.config.from_object(Config)
    if "DATABASE_REQUIRE_MANAGED" in os.environ:
        app.config["DATABASE_REQUIRE_MANAGED"] = os.environ["DATABASE_REQUIRE_MANAGED"]
    try:
        db_uri = _configured_database_uri_without_fallback(app)
    except ValueError as exc:
        db_uri = None
        app.config["BACKUP_READINESS_CONFIG_ERROR"] = str(exc)
    if db_uri:
        from musicround.helpers.database_config import database_backend, database_summary

        app.config["SQLALCHEMY_DATABASE_URI"] = db_uri
        app.config["DATABASE_BACKEND"] = database_backend(db_uri)
        app.config["DATABASE_URI_REDACTED"] = database_summary(db_uri)["redacted_uri"]
    return app


def _configured_database_uri_without_fallback(app):
    """Resolve explicit database config without creating the local fallback."""
    from musicround.helpers.database_config import database_uri_from_postgres_env

    configured_uri = os.environ.get("SQLALCHEMY_DATABASE_URI") or app.config.get(
        "SQLALCHEMY_DATABASE_URI"
    )
    if configured_uri:
        return configured_uri
    return database_uri_from_postgres_env(os.environ)


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

    readiness_parser = backup_subparsers.add_parser(
        'readiness',
        help='Check whether built-in app backups are valid for the configured database',
    )
    readiness_parser.add_argument(
        '--json',
        action='store_true',
        dest='json_output',
        help='Print machine-readable credential-safe backup readiness diagnostics',
    )
    
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
    cutover_plan_parser = database_subparsers.add_parser(
        'cutover-plan',
        help='Print a credential-safe managed database cutover checklist',
    )
    cutover_plan_parser.add_argument(
        '--json',
        action='store_true',
        dest='json_output',
        help='Print machine-readable credential-safe cutover steps',
    )
    manifest_audit_parser = database_subparsers.add_parser(
        'manifest-audit',
        help='Audit Kubernetes manifests for managed database cutover readiness',
    )
    manifest_audit_parser.add_argument(
        '--path',
        action='append',
        required=True,
        help='Kubernetes manifest file or directory to scan. May be repeated.',
    )
    manifest_audit_parser.add_argument(
        '--json',
        action='store_true',
        dest='json_output',
        help='Print machine-readable credential-safe audit results',
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

    scheduled_emails_parser = subparsers.add_parser(
        'scheduled-emails',
        help='Scheduled round email jobs',
    )
    scheduled_emails_subparsers = scheduled_emails_parser.add_subparsers(
        dest='scheduled_emails_action',
        help='Scheduled email action to perform',
    )
    process_due_parser = scheduled_emails_subparsers.add_parser(
        'process-due',
        help='Send due scheduled round emails from the app container',
    )
    process_due_parser.add_argument(
        '--limit',
        type=int,
        default=10,
        help='Maximum number of due exports to process, between 1 and 100.',
    )
    process_due_parser.add_argument(
        '--now',
        help='Optional ISO timestamp for deterministic smoke tests.',
    )
    process_due_parser.add_argument(
        '--json',
        action='store_true',
        dest='json_output',
        help='Print machine-readable processing results.',
    )

    deployment_parser = subparsers.add_parser('deployment', help='Deployment smoke checks')
    deployment_subparsers = deployment_parser.add_subparsers(
        dest='deployment_action',
        help='Deployment action to perform',
    )
    deployment_smoke_parser = deployment_subparsers.add_parser(
        'smoke',
        help='Run public deployment smoke checks against a QB base URL',
    )
    deployment_smoke_parser.add_argument(
        '--base-url',
        default=os.environ.get('QB_SMOKE_BASE_URL', 'https://qb.kaufdeinquiz.com'),
        help='Public QB base URL to smoke-test. Defaults to QB_SMOKE_BASE_URL or production.',
    )
    deployment_smoke_parser.add_argument(
        '--timeout',
        type=float,
        default=10.0,
        help='Per-request timeout in seconds.',
    )
    deployment_smoke_parser.add_argument(
        '--static-path',
        default='/static/favicon.ico',
        help='Static asset path that should expose cache headers.',
    )
    deployment_smoke_parser.add_argument(
        '--compression-path',
        default='/users/login',
        help='Public text-like path that should gzip when requested.',
    )
    deployment_smoke_parser.add_argument(
        '--require-hsts',
        action='store_true',
        help='Require Strict-Transport-Security even for non-HTTPS smoke targets.',
    )
    deployment_smoke_parser.add_argument(
        '--no-require-hsts',
        action='store_true',
        help='Do not require Strict-Transport-Security, useful for local HTTP smoke targets.',
    )
    deployment_smoke_parser.add_argument(
        '--json',
        action='store_true',
        dest='json_output',
        help='Print machine-readable smoke results.',
    )

    performance_parser = subparsers.add_parser('performance', help='Performance smoke checks')
    performance_subparsers = performance_parser.add_subparsers(
        dest='performance_action',
        help='Performance action to perform',
    )
    smoke_parser = performance_subparsers.add_parser(
        'smoke',
        help='Run bounded local performance checks for search, imports, rounds, and MCP-like calls',
    )
    smoke_parser.add_argument(
        '--sample-size',
        type=int,
        default=250,
        help='Synthetic playlist/song sample size, between 8 and 5000.',
    )
    smoke_parser.add_argument(
        '--synthetic',
        action='store_true',
        help='Create and clean up a temporary synthetic dataset for round-review checks.',
    )
    smoke_parser.add_argument(
        '--json',
        action='store_true',
        dest='json_output',
        help='Print machine-readable smoke results.',
    )
    smoke_parser.add_argument(
        '--search-threshold-ms',
        type=float,
        default=250.0,
        help='Maximum acceptable catalog search duration.',
    )
    smoke_parser.add_argument(
        '--import-threshold-ms',
        type=float,
        default=250.0,
        help='Maximum acceptable playlist parsing duration.',
    )
    smoke_parser.add_argument(
        '--analytics-threshold-ms',
        type=float,
        default=500.0,
        help='Maximum acceptable analytics/MCP summary duration.',
    )
    smoke_parser.add_argument(
        '--round-review-threshold-ms',
        type=float,
        default=750.0,
        help='Maximum acceptable round-review payload duration when --synthetic is used.',
    )

    notifications_parser = subparsers.add_parser('notifications', help='Notification jobs')
    notifications_subparsers = notifications_parser.add_subparsers(
        dest='notifications_action',
        help='Notification action to perform',
    )
    oauth_tokens_parser = notifications_subparsers.add_parser(
        'oauth-tokens',
        help='Warn users about expiring or broken OAuth connections',
    )
    oauth_tokens_parser.add_argument(
        '--send',
        action='store_true',
        help='Send emails. Omit for the default dry run.',
    )
    verify_email_parser = notifications_subparsers.add_parser(
        'verify-email',
        help='Validate SMTP configuration and optionally send a test email',
    )
    verify_email_parser.add_argument(
        '--recipient',
        help='Recipient for the optional test email. Defaults to MAIL_RECIPIENT.',
    )
    verify_email_parser.add_argument(
        '--send',
        action='store_true',
        help='Send a test email. Omit for the default configuration-only dry run.',
    )
    admin_summary_parser = notifications_subparsers.add_parser(
        'admin-summary',
        help='Summarize actionable notification and repair work for administrators',
    )
    admin_summary_parser.add_argument(
        '--recipient',
        help='Recipient for the optional admin summary email. Defaults to MAIL_RECIPIENT.',
    )
    admin_summary_parser.add_argument(
        '--window-hours',
        type=int,
        default=24,
        help='How many recent hours of failed round exports to include.',
    )
    admin_summary_parser.add_argument(
        '--limit',
        type=int,
        default=10,
        help='Maximum number of rows to include per summary section.',
    )
    admin_summary_parser.add_argument(
        '--send',
        action='store_true',
        help='Send the admin summary email. Omit for the default dry run.',
    )
    
    # Parse the arguments
    args = parser.parse_args()
    
    # Run the command
    if args.command == 'backup':
        if args.backup_action == 'readiness':
            app = _create_backup_readiness_cli_app()
        else:
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
            elif args.backup_action == 'readiness':
                from musicround.helpers.backup_helper import backup_readiness_report

                result = backup_readiness_report()
                if args.json_output:
                    print(json.dumps(result, indent=2, sort_keys=True))
                else:
                    print(f"Backup readiness: {result['status']}")
                    print(f"Database backend: {result['database_backend']}")
                    print(
                        "Application backup supported: "
                        f"{result['application_backup_supported']}"
                    )
                    database_backup = result.get("database_backup") or {}
                    print(
                        "Native database backup required: "
                        f"{database_backup.get('required', False)}"
                    )
                    if database_backup.get("strategy"):
                        print(f"Database backup strategy: {database_backup['strategy']}")
                    commands = database_backup.get("recommended_commands") or []
                    if commands:
                        print("Recommended database backup commands:")
                        for command in commands:
                            print(f"- {command}")
                    for issue in result["issues"]:
                        print(f"- {issue['severity']}: {issue['code']}")
                        print(f"  {issue['message']}")
                    print(f"Next action: {result['next_action']}")
                return 0 if result["ok"] else 1
    elif args.command == 'database':
        if args.database_action == 'manifest-audit':
            from musicround.helpers.kubernetes_database_audit import (
                audit_kubernetes_database_manifests,
            )

            try:
                result = audit_kubernetes_database_manifests(args.path)
            except RuntimeError as exc:
                print(f"Database manifest audit error: {exc}", file=sys.stderr)
                return 78
            if args.json_output:
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(f"Database manifest audit {result['status']}:")
                for issue in result["issues"]:
                    print(
                        f"- {issue['severity']}: {issue['code']} "
                        f"{issue['resource'] if issue.get('resource') else ''}"
                    )
                    print(f"  {issue['message']}")
            return 0 if result["ok"] else 1

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
            database_cutover_plan,
            database_uri_overrides_postgres_env,
            is_legacy_data_sqlite_uri,
            postgres_env_readiness,
        )

        app = Flask(__name__)
        app.config.from_object(Config)
        if "SQLALCHEMY_DATABASE_URI" not in os.environ:
            app.config["SQLALCHEMY_DATABASE_URI"] = None
        json_output = bool(getattr(args, "json_output", False))
        allow_sqlite = bool(getattr(args, "allow_sqlite", False))
        configured_managed_required = bool(app.config.get('DATABASE_REQUIRE_MANAGED'))
        preflight_requires_managed = args.database_action == 'preflight' and not allow_sqlite
        diagnostic_managed_required = preflight_requires_managed or configured_managed_required
        config_error = None
        if json_output or args.database_action == 'cutover-plan':
            try:
                db_uri = _configured_database_uri_without_fallback(app)
            except ValueError as exc:
                if args.database_action == 'cutover-plan':
                    db_uri = None
                    config_error = str(exc)
                else:
                    print(f"Database configuration error: {exc}", file=sys.stderr)
                    return 78
            if db_uri:
                app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
        else:
            if args.database_action == 'preflight':
                app.config['DATABASE_REQUIRE_MANAGED'] = preflight_requires_managed
            try:
                _configure_database_uri(app)
            except RuntimeError as exc:
                print(f"Database configuration error: {exc}", file=sys.stderr)
                return 78
            db_uri = app.config.get('SQLALCHEMY_DATABASE_URI')
        summary = database_summary(db_uri)
        readiness = postgres_env_readiness(os.environ)
        issues = []
        if config_error:
            issues.append(
                {
                    "code": "postgres_env_incomplete",
                    "severity": "error",
                    "message": config_error,
                    "hint": "complete the missing PG* secret keys before cutover",
                }
            )
        if diagnostic_managed_required and summary["backend"] == "unconfigured":
            issues.append(
                {
                    "code": "managed_database_requirement_failed",
                    "severity": "error",
                    "message": "managed database is required but no database is configured",
                    "hint": (
                        "configure a managed SQL URI or complete PG* credentials "
                        "via secrets for production"
                    ),
                }
            )
        elif diagnostic_managed_required and summary["backend"] == "sqlite":
            issues.append(
                {
                    "code": "managed_database_requirement_failed",
                    "severity": "error",
                    "message": "managed database is required but SQLite is configured",
                    "hint": (
                        "configure a managed SQL URI or complete PG* credentials "
                        "via secrets for production"
                    ),
                }
            )
        elif is_legacy_data_sqlite_uri(db_uri):
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
        if database_uri_overrides_postgres_env(os.environ):
            issues.append(
                {
                    "code": "database_uri_overrides_postgres_env",
                    "severity": "warning",
                    "message": (
                        "SQLALCHEMY_DATABASE_URI overrides complete split "
                        "PostgreSQL configuration"
                    ),
                    "hint": (
                        "remove or blank SQLALCHEMY_DATABASE_URI before relying "
                        "on PG* managed database secrets during cutover"
                    ),
                }
            )
        diagnostics = {
            "ok": not any(issue["severity"] == "error" for issue in issues),
            "status": (
                "error"
                if any(issue["severity"] == "error" for issue in issues)
                else "warning" if issues else "ok"
            ),
            "managed_required": diagnostic_managed_required,
            "database": summary,
            "postgres_env": readiness,
            "issues": issues,
        }
        if args.database_action == 'cutover-plan':
            plan = database_cutover_plan(diagnostics)
            if json_output:
                print(json.dumps(plan, indent=2, sort_keys=True))
            else:
                print(f"Database cutover status: {plan['status']}")
                print(f"Database backend: {summary['backend']}")
                print(f"Cutover ready: {plan['ok']}")
                for item in plan["steps"]:
                    print(f"- [{item['status']}] {item['title']}: {item['hint']}")
                print(f"Next action: {plan['next_action']}")
            return 0
        if json_output:
            print(json.dumps(diagnostics, indent=2, sort_keys=True))
            if any(issue["severity"] == "error" for issue in issues):
                return 78
            if args.database_action == 'preflight' and issues and not allow_sqlite:
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
        if database_uri_overrides_postgres_env(os.environ):
            print(
                "Warning: SQLALCHEMY_DATABASE_URI overrides complete split "
                "PostgreSQL configuration; remove or blank it before relying "
                "on PG* managed database secrets during cutover."
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
    elif args.command == 'scheduled-emails':
        if args.scheduled_emails_action == 'process-due':
            with contextlib.redirect_stdout(sys.stderr):
                app = create_app()
            with app.app_context():
                from musicround.services.automation import (
                    AutomationError,
                    process_due_scheduled_round_emails,
                )

                try:
                    result = process_due_scheduled_round_emails(
                        now=args.now,
                        limit=args.limit,
                    )
                except AutomationError as exc:
                    print(f"Scheduled email processing error: {exc}", file=sys.stderr)
                    return 78
                if args.json_output:
                    print(json.dumps(result, indent=2, sort_keys=True))
                else:
                    print(
                        "Scheduled email processing complete: "
                        f"{result['processed_count']} export(s) processed."
                    )
                return 0
    elif args.command == 'deployment':
        if args.deployment_action == 'smoke':
            from musicround.helpers.deployment_smoke import run_deployment_smoke

            require_hsts = None
            if args.require_hsts:
                require_hsts = True
            if args.no_require_hsts:
                require_hsts = False
            try:
                result = run_deployment_smoke(
                    args.base_url,
                    timeout=args.timeout,
                    require_hsts=require_hsts,
                    static_path=args.static_path,
                    compression_path=args.compression_path,
                )
            except ValueError as exc:
                print(f"Deployment smoke error: {exc}", file=sys.stderr)
                return 78
            if args.json_output:
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                status = "passed" if result["ok"] else "failed"
                print(f"Deployment smoke {status} for {result['base_url']}:")
                for check in result["checks"]:
                    check_status = "ok" if check["ok"] else "failed"
                    print(f"- {check['name']}: {check['message']} [{check_status}]")
            return 0 if result["ok"] else 1
    elif args.command == 'performance':
        with contextlib.redirect_stdout(sys.stderr):
            app = create_app()
        with app.app_context():
            if args.performance_action == 'smoke':
                from musicround.helpers.performance_smoke import run_performance_smoke

                try:
                    result = run_performance_smoke(
                        sample_size=args.sample_size,
                        include_synthetic=args.synthetic,
                        search_threshold_ms=args.search_threshold_ms,
                        import_threshold_ms=args.import_threshold_ms,
                        analytics_threshold_ms=args.analytics_threshold_ms,
                        round_review_threshold_ms=args.round_review_threshold_ms,
                    )
                except ValueError as exc:
                    print(f"Performance smoke error: {exc}", file=sys.stderr)
                    return 78
                if args.json_output:
                    print(json.dumps(result, indent=2, sort_keys=True))
                else:
                    status = "passed" if result["ok"] else "failed"
                    print(f"Performance smoke {status}:")
                    for check in result["checks"]:
                        check_status = "ok" if check["ok"] else "slow"
                        print(
                            f"- {check['name']}: {check['duration_ms']}ms "
                            f"/ {check['threshold_ms']}ms [{check_status}]"
                        )
                return 0 if result["ok"] else 1
    elif args.command == 'notifications':
        with contextlib.redirect_stdout(sys.stderr):
            app = create_app()
        with app.app_context():
            if args.notifications_action == 'oauth-tokens':
                from musicround.helpers.oauth_notifications import send_oauth_token_notifications

                result = send_oauth_token_notifications(dry_run=not args.send)
                print(json.dumps(result, indent=2, sort_keys=True))
                return 1 if result.get("failed_count") else 0
            if args.notifications_action == 'verify-email':
                from musicround.helpers.email_helper import verify_email_delivery

                result = verify_email_delivery(recipient=args.recipient, send=args.send)
                print(json.dumps(result, indent=2, sort_keys=True))
                return 0 if result.get("ok") else 1
            if args.notifications_action == 'admin-summary':
                from musicround.helpers.notification_summary import send_notification_admin_summary

                result = send_notification_admin_summary(
                    recipient=args.recipient,
                    window_hours=args.window_hours,
                    limit=args.limit,
                    dry_run=not args.send,
                )
                print(json.dumps(result, indent=2, sort_keys=True))
                return 1 if result.get("failed") else 0
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
