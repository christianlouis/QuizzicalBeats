"""Tests for the management CLI."""

import json
import sqlite3
import sys

from sqlalchemy import create_engine


def test_health_check_command_outputs_public_safe_json(app, monkeypatch, capsys):
    """The documented health CLI should share the /healthz payload."""
    import run

    monkeypatch.setattr(sys, "argv", ["run.py", "health", "check"])
    monkeypatch.setattr(run, "create_app", lambda: app)

    exit_code = run.main()
    captured = capsys.readouterr()
    output = captured.out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["services"]["database"]["status"] == "ok"
    assert "password" not in output.lower()
    assert "token" not in output.lower()


def test_notifications_oauth_tokens_command_defaults_to_dry_run(app, monkeypatch, capsys):
    """OAuth token notification CLI previews by default."""
    import run

    monkeypatch.setattr(sys, "argv", ["run.py", "notifications", "oauth-tokens"])
    monkeypatch.setattr(run, "create_app", lambda: app)

    exit_code = run.main()
    captured = capsys.readouterr()
    output = captured.out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["dry_run"] is True
    assert payload["candidate_count"] == 0
    assert "redaction-fixture" not in output
    assert "token=secret" not in output


def test_notifications_verify_email_command_defaults_to_dry_run(app, monkeypatch, capsys):
    """Email verification CLI should be safe by default."""
    import run

    app.config.update(
        MAIL_HOST="smtp.example.test",
        MAIL_PORT=587,
        MAIL_USERNAME="mailer",
        MAIL_PASSWORD="secret",
        MAIL_SENDER="sender@example.test",
        MAIL_RECIPIENT="admin@example.test",
    )
    monkeypatch.setattr(sys, "argv", ["run.py", "notifications", "verify-email"])
    monkeypatch.setattr(run, "create_app", lambda: app)

    exit_code = run.main()
    captured = capsys.readouterr()
    output = captured.out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["dry_run"] is True
    assert payload["configured"] is True
    assert payload["sent"] is False
    assert payload["recipient"] == "admin@example.test"
    assert "redaction-fixture" not in output
    assert "token=secret" not in output


def test_notifications_admin_summary_command_defaults_to_dry_run(app, monkeypatch, capsys):
    """Admin notification summaries should preview as safe JSON by default."""
    import run

    app.config["MAIL_RECIPIENT"] = "admin@example.test"
    monkeypatch.setattr(sys, "argv", ["run.py", "notifications", "admin-summary"])
    monkeypatch.setattr(run, "create_app", lambda: app)

    exit_code = run.main()
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["dry_run"] is True
    assert payload["sent"] is False
    assert payload["recipient"] == "admin@example.test"
    assert "service_health_issue_count" in payload["summary"]
    assert "backup_readiness_issue_count" in payload["summary"]
    assert payload["summary"]["actionable_count"] == (
        payload["summary"]["service_health_issue_count"]
        + payload["summary"]["backup_readiness_issue_count"]
    )
    assert "redaction-fixture" not in output
    assert "token=secret" not in output


def test_scheduled_emails_process_due_command_outputs_json(app, monkeypatch, capsys):
    """Scheduled email CLI should run in the app container and emit safe JSON."""
    import run
    from musicround.services import automation

    def fake_process_due_scheduled_round_emails(now=None, limit=10):
        return {
            "processed_count": 0,
            "now": now or "2026-07-08T20:00:00Z",
            "results": [],
            "limit": limit,
        }

    monkeypatch.setattr(run, "create_app", lambda: app)
    monkeypatch.setattr(
        automation,
        "process_due_scheduled_round_emails",
        fake_process_due_scheduled_round_emails,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "scheduled-emails",
            "process-due",
            "--now",
            "2026-07-08T20:00:00Z",
            "--limit",
            "25",
            "--json",
        ],
    )

    exit_code = run.main()
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["processed_count"] == 0
    assert payload["limit"] == 25
    assert payload["now"] == "2026-07-08T20:00:00Z"
    assert "secret" not in output.lower()


def test_scheduled_emails_process_due_command_reports_validation_errors(
    app,
    monkeypatch,
    capsys,
):
    """Scheduled email CLI should map automation validation errors to EX_CONFIG."""
    import run

    monkeypatch.setattr(run, "create_app", lambda: app)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run.py", "scheduled-emails", "process-due", "--limit", "0"],
    )

    exit_code = run.main()
    captured = capsys.readouterr()

    assert exit_code == 78
    assert "limit must be between 1 and 100" in captured.err
    assert "Traceback" not in captured.err


def test_backup_readiness_command_outputs_json_for_sqlite(app, monkeypatch, capsys, tmp_path):
    """Backup readiness CLI should allow the built-in backup path for SQLite."""
    import run

    db_path = tmp_path / "song_data.db"
    db_path.write_bytes(b"sqlite placeholder")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["DATABASE_BACKEND"] = "sqlite"
    monkeypatch.setattr(run, "create_app", lambda: app)
    monkeypatch.setattr(sys, "argv", ["run.py", "backup", "readiness", "--json"])

    exit_code = run.main()
    captured = capsys.readouterr()
    output = captured.out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["application_backup_supported"] is True
    assert payload["database_backup"]["required"] is False
    assert payload["database_backup"]["strategy"] == "application_zip"
    assert payload["recommended_scheduler_command"] == "python /app/run.py backup create --auto"
    assert str(db_path) not in output


def test_backup_readiness_command_blocks_managed_database_without_secret_leak(
    monkeypatch,
    capsys,
):
    """Backup readiness CLI should reject app ZIP backups for managed SQL."""
    import run

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.setenv(
        "SQLALCHEMY_DATABASE_URI",
        "postgresql://qb_user:redaction-fixture@postgres.example:5432/quizzicalbeats"
    )
    monkeypatch.setattr(sys, "argv", ["run.py", "backup", "readiness", "--json"])

    exit_code = run.main()
    captured = capsys.readouterr()
    output = captured.out
    payload = json.loads(output)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["issues"][0]["code"] == "managed_database_requires_external_backup"
    assert payload["database_backup"]["required"] is True
    assert payload["database_backup"]["strategy"] == "postgresql_native"
    assert "PGPASSWORD" in payload["database_backup"]["credential_env_keys"]
    assert any(
        "pg_dump" in command
        for command in payload["database_backup"]["recommended_commands"]
    )
    assert payload["recommended_scheduler_command"] is None
    assert "redaction-fixture" not in output
    assert "postgresql://" not in output
    assert "Traceback" not in captured.err


def test_backup_readiness_command_reports_managed_guard_without_app_start_failure(
    monkeypatch,
    capsys,
):
    """Backup readiness should fail closed as JSON even when the app would reject SQLite."""
    import run

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", "sqlite:////data/song_data.db")
    monkeypatch.setenv("DATABASE_REQUIRE_MANAGED", "true")
    monkeypatch.setattr(sys, "argv", ["run.py", "backup", "readiness", "--json"])

    exit_code = run.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["issues"][0]["code"] == "managed_database_requirement_failed"
    assert payload["recommended_scheduler_command"] is None
    assert "/data/song_data.db" not in captured.out
    assert "Traceback" not in captured.err


def test_performance_smoke_command_outputs_json(app, monkeypatch, capsys):
    """The performance smoke CLI should provide agent-readable JSON output."""
    import run

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "performance",
            "smoke",
            "--json",
            "--synthetic",
            "--sample-size",
            "12",
            "--search-threshold-ms",
            "10000",
            "--import-threshold-ms",
            "10000",
            "--analytics-threshold-ms",
            "10000",
            "--round-review-threshold-ms",
            "10000",
        ],
    )
    monkeypatch.setattr(run, "create_app", lambda: app)

    exit_code = run.main()
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["synthetic"] is True
    assert "secret" not in output.lower()


def test_performance_smoke_command_rejects_invalid_sample_size(app, monkeypatch, capsys):
    """The CLI should fail fast with a clear message for invalid sample sizes."""
    import run

    monkeypatch.setattr(sys, "argv", ["run.py", "performance", "smoke", "--sample-size", "2"])
    monkeypatch.setattr(run, "create_app", lambda: app)

    exit_code = run.main()
    captured = capsys.readouterr()

    assert exit_code == 78
    assert "sample_size" in captured.err
    assert "Traceback" not in captured.err


def test_deployment_smoke_command_outputs_json(monkeypatch, capsys):
    """Deployment smoke CLI should expose agent-readable deployment checks."""
    import run

    def fake_smoke(base_url, **kwargs):
        return {
            "ok": True,
            "base_url": base_url.rstrip("/") + "/",
            "checks": [{"name": "healthz", "ok": True, "message": "ok"}],
            "failed_checks": [],
        }

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "deployment",
            "smoke",
            "--base-url",
            "https://qb.example.test",
            "--json",
        ],
    )
    monkeypatch.setattr("musicround.helpers.deployment_smoke.run_deployment_smoke", fake_smoke)

    exit_code = run.main()
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["base_url"] == "https://qb.example.test/"


def test_deployment_smoke_command_rejects_invalid_base_url(monkeypatch, capsys):
    """Deployment smoke CLI should return a clear config error for bad targets."""
    import run

    monkeypatch.setattr(sys, "argv", ["run.py", "deployment", "smoke", "--base-url", "/relative"])

    exit_code = run.main()
    captured = capsys.readouterr()

    assert exit_code == 78
    assert "base_url" in captured.err
    assert "Traceback" not in captured.err


def test_database_status_warns_for_legacy_data_sqlite(monkeypatch, capsys):
    """The database runbook command should flag the legacy production SQLite file."""
    import run

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", "sqlite:////data/song_data.db")
    monkeypatch.delenv("DATABASE_REQUIRE_MANAGED", raising=False)
    monkeypatch.setattr(sys, "argv", ["run.py", "database", "status"])

    exit_code = run.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Database backend: sqlite" in output
    assert "Managed database required: False" in output
    assert "legacy /data SQLite database is configured" in output
    assert "complete PG* credentials" in output


def test_database_status_json_reports_legacy_sqlite_safely(monkeypatch, capsys):
    """Machine-readable database status should be safe for agent workflows."""
    import run

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", "sqlite:////data/song_data.db")
    monkeypatch.delenv("DATABASE_REQUIRE_MANAGED", raising=False)
    monkeypatch.setattr(sys, "argv", ["run.py", "database", "status", "--json"])

    exit_code = run.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["status"] == "warning"
    assert payload["database"]["redacted_uri"] == "sqlite:///[local-file]"
    assert payload["issues"][0]["code"] == "legacy_sqlite_data_store"
    assert "/data/song_data.db" not in captured.out


def test_database_status_json_reports_unconfigured_without_fallback(
    monkeypatch,
    capsys,
    tmp_path,
):
    """JSON status should not create or reveal the local SQLite fallback path."""
    import run

    data_dir = tmp_path / "data"
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
    monkeypatch.delenv("DATABASE_REQUIRE_MANAGED", raising=False)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["run.py", "database", "status", "--json"])

    exit_code = run.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["database"]["backend"] == "unconfigured"
    assert payload["database"]["redacted_uri"] == "unconfigured"
    assert str(data_dir) not in captured.out
    assert str(data_dir) not in captured.err
    assert not data_dir.exists()


def test_database_preflight_json_blocks_unconfigured_without_fallback(
    monkeypatch,
    capsys,
    tmp_path,
):
    """JSON preflight should fail managed cutover without creating SQLite state."""
    import run

    data_dir = tmp_path / "data"
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
    monkeypatch.delenv("DATABASE_REQUIRE_MANAGED", raising=False)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["run.py", "database", "preflight", "--json"])

    exit_code = run.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 78
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["managed_required"] is True
    assert payload["database"]["backend"] == "unconfigured"
    assert payload["issues"][0]["code"] == "managed_database_requirement_failed"
    assert str(data_dir) not in captured.out
    assert str(data_dir) not in captured.err
    assert not data_dir.exists()
    assert "Traceback" not in captured.err


def test_database_preflight_json_blocks_legacy_sqlite(monkeypatch, capsys):
    """JSON preflight should keep the same blocking semantics as text output."""
    import run

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", "sqlite:////data/song_data.db")
    monkeypatch.delenv("DATABASE_REQUIRE_MANAGED", raising=False)
    monkeypatch.setattr(sys, "argv", ["run.py", "database", "preflight", "--json"])

    exit_code = run.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 78
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["managed_required"] is True
    assert payload["issues"][0]["code"] == "managed_database_requirement_failed"
    assert "/data/song_data.db" not in captured.out
    assert "Traceback" not in captured.err


def test_database_status_json_reports_managed_guard_error(monkeypatch, capsys):
    """JSON status should expose managed-DB violations without a traceback."""
    import run

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", "sqlite:////data/song_data.db")
    monkeypatch.setenv("DATABASE_REQUIRE_MANAGED", "true")
    from musicround.config import Config
    monkeypatch.setattr(Config, "DATABASE_REQUIRE_MANAGED", True)
    monkeypatch.setattr(sys, "argv", ["run.py", "database", "status", "--json"])

    exit_code = run.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 78
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["managed_required"] is True
    assert payload["issues"][0]["code"] == "managed_database_requirement_failed"
    assert "/data/song_data.db" not in captured.out
    assert "Traceback" not in captured.err


def test_database_status_returns_safe_error_when_managed_guard_fails(monkeypatch, capsys):
    """The database runbook command should fail without a Python traceback."""
    import run

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", "sqlite:////data/song_data.db")
    monkeypatch.setenv("DATABASE_REQUIRE_MANAGED", "true")
    from musicround.config import Config
    monkeypatch.setattr(Config, "DATABASE_REQUIRE_MANAGED", True)
    monkeypatch.setattr(sys, "argv", ["run.py", "database", "status"])

    exit_code = run.main()
    captured = capsys.readouterr()

    assert exit_code == 78
    assert "Database configuration error:" in captured.err
    assert "points at SQLite" in captured.err
    assert "Traceback" not in captured.err
    assert "/data/song_data.db" not in captured.err


def test_database_preflight_blocks_legacy_sqlite_by_default(monkeypatch, capsys):
    """The managed DB cutover preflight should fail before SQLite reaches prod."""
    import run

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", "sqlite:////data/song_data.db")
    monkeypatch.delenv("DATABASE_REQUIRE_MANAGED", raising=False)
    monkeypatch.setattr(sys, "argv", ["run.py", "database", "preflight"])

    exit_code = run.main()
    captured = capsys.readouterr()

    assert exit_code == 78
    assert "Database configuration error:" in captured.err
    assert "points at SQLite" in captured.err
    assert "Traceback" not in captured.err
    assert "/data/song_data.db" not in captured.err


def test_database_preflight_can_report_sqlite_without_blocking(monkeypatch, capsys):
    """Operators can inspect early migration state before the managed cutover."""
    import run
    from musicround.config import Config

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", "sqlite:////data/song_data.db")
    monkeypatch.setenv("DATABASE_REQUIRE_MANAGED", "true")
    monkeypatch.setattr(Config, "DATABASE_REQUIRE_MANAGED", True)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run.py", "database", "preflight", "--allow-sqlite"],
    )

    exit_code = run.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Database backend: sqlite" in output
    assert "Managed database required: False" in output
    assert "legacy /data SQLite database is configured" in output
    assert "Database preflight passed." in output


def test_database_preflight_accepts_complete_pg_env(monkeypatch, capsys):
    """A complete PG* setup should pass without exposing credentials."""
    import run

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
    monkeypatch.setenv("PGHOST", "postgres.example")
    monkeypatch.setenv("PGDATABASE", "quizzicalbeats")
    monkeypatch.setenv("PGUSER", "qb_user")
    monkeypatch.setenv("PGPASSWORD", "redaction-fixture-value")
    monkeypatch.setenv("PGSSLMODE", "require")
    monkeypatch.setattr(sys, "argv", ["run.py", "database", "preflight"])

    exit_code = run.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Database backend: postgresql" in captured.out
    assert (
        "PostgreSQL env present: PGHOST, PGDATABASE, PGUSER, PGPASSWORD, "
        "PGSSLMODE"
    ) in captured.out
    assert "Database preflight passed." in captured.out
    assert "redaction-fixture-value" not in captured.out
    assert "redaction-fixture-value" not in captured.err


def test_database_status_json_warns_when_full_uri_masks_pg_env(monkeypatch, capsys):
    """Status should flag the cutover trap where a full URI hides PG* secrets."""
    import run

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", "sqlite:////data/song_data.db")
    monkeypatch.delenv("DATABASE_REQUIRE_MANAGED", raising=False)
    monkeypatch.setenv("PGHOST", "postgres.example")
    monkeypatch.setenv("PGDATABASE", "quizzicalbeats")
    monkeypatch.setenv("PGUSER", "qb_user")
    monkeypatch.setenv("PGPASSWORD", "redaction-fixture-value")
    monkeypatch.setattr(sys, "argv", ["run.py", "database", "status", "--json"])

    exit_code = run.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["status"] == "warning"
    assert [issue["code"] for issue in payload["issues"]] == [
        "legacy_sqlite_data_store",
        "database_uri_overrides_postgres_env",
    ]
    assert payload["postgres_env"]["complete"] is True
    assert "redaction-fixture-value" not in captured.out
    assert "postgres.example" not in captured.out
    assert "/data/song_data.db" not in captured.out


def test_database_status_prints_uri_override_warning(monkeypatch, capsys):
    """Text diagnostics should tell operators why PG* is not taking effect."""
    import run

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", "sqlite:////data/song_data.db")
    monkeypatch.delenv("DATABASE_REQUIRE_MANAGED", raising=False)
    monkeypatch.setenv("PGHOST", "postgres.example")
    monkeypatch.setenv("PGDATABASE", "quizzicalbeats")
    monkeypatch.setenv("PGUSER", "qb_user")
    monkeypatch.setenv("PGPASSWORD", "redaction-fixture-value")
    monkeypatch.setattr(sys, "argv", ["run.py", "database", "status"])

    exit_code = run.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "SQLALCHEMY_DATABASE_URI overrides complete split PostgreSQL" in captured.out
    assert "legacy /data SQLite database is configured" in captured.out
    assert "redaction-fixture-value" not in captured.out
    assert "postgres.example" not in captured.out
    assert "/data/song_data.db" not in captured.out


def test_database_preflight_reports_missing_pg_keys_safely(monkeypatch, capsys):
    """Incomplete PG* setup should fail with key names, not secret values."""
    import run

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
    monkeypatch.setenv("PGHOST", "postgres.example")
    monkeypatch.setenv("PGDATABASE", "quizzicalbeats")
    monkeypatch.delenv("PGUSER", raising=False)
    monkeypatch.delenv("PGPASSWORD", raising=False)
    monkeypatch.setattr(sys, "argv", ["run.py", "database", "preflight"])

    exit_code = run.main()
    captured = capsys.readouterr()

    assert exit_code == 78
    assert "PostgreSQL environment is incomplete" in captured.err
    assert "PGPASSWORD" in captured.err
    assert "PGUSER" in captured.err
    assert "postgres.example" not in captured.err
    assert "Traceback" not in captured.err


def test_database_cutover_plan_json_blocks_unconfigured_without_fallback(
    monkeypatch,
    capsys,
    tmp_path,
):
    """Cutover planning should not create the local SQLite fallback."""
    import run

    data_dir = tmp_path / "data"
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
    monkeypatch.delenv("DATABASE_REQUIRE_MANAGED", raising=False)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["run.py", "database", "cutover-plan", "--json"])

    exit_code = run.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["database"]["backend"] == "unconfigured"
    assert "configure_managed_database" in payload["blocked_steps"]
    assert str(data_dir) not in captured.out
    assert str(data_dir) not in captured.err
    assert not data_dir.exists()


def test_database_cutover_plan_json_accepts_complete_pg_env(monkeypatch, capsys):
    """A complete PG* setup should produce a ready credential-safe plan."""
    import run

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
    monkeypatch.setenv("PGHOST", "postgres.example")
    monkeypatch.setenv("PGDATABASE", "quizzicalbeats")
    monkeypatch.setenv("PGUSER", "qb_user")
    monkeypatch.setenv("PGPASSWORD", "redaction-fixture-value")
    monkeypatch.setenv("PGSSLMODE", "require")
    monkeypatch.setattr(sys, "argv", ["run.py", "database", "cutover-plan", "--json"])

    exit_code = run.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["status"] == "ready"
    assert payload["database"]["backend"] == "postgresql"
    assert payload["blocked_steps"] == []
    assert "dry_run_sqlite_migration" in payload["ready_steps"]
    assert "redaction-fixture-value" not in captured.out
    assert "Traceback" not in captured.err


def test_database_cutover_plan_reports_incomplete_pg_env_safely(monkeypatch, capsys):
    """The cutover plan should keep going and report missing PG* key names."""
    import run

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
    monkeypatch.setenv("PGHOST", "postgres.example")
    monkeypatch.setenv("PGDATABASE", "quizzicalbeats")
    monkeypatch.delenv("PGUSER", raising=False)
    monkeypatch.delenv("PGPASSWORD", raising=False)
    monkeypatch.setattr(sys, "argv", ["run.py", "database", "cutover-plan", "--json"])

    exit_code = run.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["issues"][0]["code"] == "postgres_env_incomplete"
    assert "PGPASSWORD" in payload["issues"][0]["message"]
    assert "PGUSER" in payload["issues"][0]["message"]
    assert "configure_managed_database" in payload["blocked_steps"]
    assert "postgres.example" not in captured.out
    assert "Traceback" not in captured.err


def test_database_manifest_audit_json_reports_legacy_sqlite(monkeypatch, capsys, tmp_path):
    """Manifest audit should flag SQLite cutover blockers without exposing raw paths."""
    import run

    manifest = tmp_path / "qb.yaml"
    manifest.write_text(
        """
apiVersion: v1
kind: ConfigMap
metadata:
  name: quizzicalbeats-config
data:
  SQLALCHEMY_DATABASE_URI: sqlite:////data/song_data.db
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: quizzicalbeats-secrets
spec:
  target:
    name: quizzicalbeats-secrets
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: quizzicalbeats
spec:
  template:
    spec:
      containers:
        - name: web
          envFrom:
            - configMapRef:
                name: quizzicalbeats-config
            - secretRef:
                name: quizzicalbeats-secrets
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: quizzicalbeats-mcp
spec:
  template:
    spec:
      containers:
        - name: mcp
          envFrom:
            - configMapRef:
                name: quizzicalbeats-config
            - secretRef:
                name: quizzicalbeats-secrets
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: quizzicalbeats-backup
spec:
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              envFrom:
                - configMapRef:
                    name: quizzicalbeats-config
                - secretRef:
                    name: quizzicalbeats-secrets
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["run.py", "database", "manifest-audit", "--path", str(manifest), "--json"],
    )

    exit_code = run.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert payload["status"] == "blocked"
    assert payload["blocked_issues"][0]["code"] == "legacy_sqlite_configmap"
    assert "/data/song_data.db" not in captured.out
    assert "Traceback" not in captured.err


def test_database_migrate_sqlite_refuses_sqlite_target_by_default(
    monkeypatch,
    capsys,
    tmp_path,
):
    """The migration command should not copy into SQLite unless it is a local test."""
    import run

    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _create_source_sqlite(source, songs=1)

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", f"sqlite:///{target}")
    monkeypatch.setattr(
        sys,
        "argv",
        ["run.py", "database", "migrate-sqlite", "--source", str(source)],
    )

    exit_code = run.main()
    captured = capsys.readouterr()

    assert exit_code == 78
    assert "Refusing to migrate into a SQLite target" in captured.err
    assert str(source) not in captured.out
    assert str(target) not in captured.out


def test_database_migrate_sqlite_dry_run_reports_safe_counts(
    monkeypatch,
    capsys,
    tmp_path,
):
    """Dry-run migration output should be useful and credential-safe."""
    import run

    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _create_source_sqlite(source, songs=1)

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", f"sqlite:///{target}")
    monkeypatch.setattr(
        run,
        "create_app",
        lambda: (_ for _ in ()).throw(AssertionError("full app factory called")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "database",
            "migrate-sqlite",
            "--source",
            str(source),
            "--allow-sqlite-target",
        ],
    )

    exit_code = run.main()
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["mode"] == "dry-run"
    assert payload["target"] == "sqlite:///[local-file]"
    assert payload["source"] == "sqlite:///[source-file]"
    assert payload["total_source_rows"] == 1
    assert payload["total_target_rows_after"] is None
    assert _table_payload(payload, "song")["source_rows"] == 1
    assert str(source) not in output
    assert str(target) not in output


def test_database_migrate_sqlite_execute_copies_rows(
    monkeypatch,
    capsys,
    tmp_path,
):
    """Explicit execution should copy rows into an empty configured target."""
    import run
    from musicround.helpers import database_migration

    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _create_source_sqlite(source, songs=2)

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", f"sqlite:///{target}")
    monkeypatch.setattr(database_migration, "COPY_BATCH_SIZE", 1)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "database",
            "migrate-sqlite",
            "--source",
            str(source),
            "--allow-sqlite-target",
            "--execute",
        ],
    )

    exit_code = run.main()
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["mode"] == "execute"
    assert payload["total_target_rows_after"] == 2
    assert _table_payload(payload, "song")["target_rows_after"] == 2
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT title FROM song").fetchone()[0] == "Test Song"


def test_database_migrate_sqlite_execute_reports_existing_target_rows(
    monkeypatch,
    capsys,
    tmp_path,
):
    """Execute output should preserve per-table pre-copy counts."""
    import run

    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _create_source_sqlite(source, songs=2)
    _create_source_sqlite(target, songs=1)

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", f"sqlite:///{target}")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "database",
            "migrate-sqlite",
            "--source",
            str(source),
            "--allow-sqlite-target",
            "--execute",
            "--replace-target",
        ],
    )

    exit_code = run.main()
    output = capsys.readouterr().out
    payload = json.loads(output)
    song_payload = _table_payload(payload, "song")

    assert exit_code == 0
    assert payload["total_target_rows_before"] == 1
    assert song_payload["target_rows_before"] == 1
    assert song_payload["target_rows_after"] == 2


def _create_source_sqlite(path, *, songs: int) -> None:
    from musicround import db
    import musicround.models  # noqa: F401

    engine = create_engine(f"sqlite:///{path}")
    db.metadata.create_all(bind=engine)
    if songs:
        with engine.begin() as connection:
            for index in range(songs):
                connection.execute(
                    db.metadata.tables["song"].insert().values(
                        title="Test Song" if index == 0 else f"Test Song {index + 1}",
                        artist="Test Artist",
                    )
                )
    engine.dispose()


def _table_payload(payload, table_name):
    return next(table for table in payload["tables"] if table["table"] == table_name)
