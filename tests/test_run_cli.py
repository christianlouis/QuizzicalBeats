"""Tests for the management CLI."""

import json
import sys


def test_health_check_command_outputs_public_safe_json(app, monkeypatch, capsys):
    """The documented health CLI should share the /healthz payload."""
    import run

    monkeypatch.setattr(sys, "argv", ["run.py", "health", "check"])
    monkeypatch.setattr(run, "create_app", lambda: app)

    exit_code = run.main()
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["services"]["database"]["status"] == "ok"
    assert "password" not in output.lower()
    assert "token" not in output.lower()


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

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch.setenv("AUTOMATION_TOKEN", "test-automation-token-for-testing")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", "sqlite:////data/song_data.db")
    monkeypatch.setattr(
        sys,
        "argv",
        ["run.py", "database", "preflight", "--allow-sqlite"],
    )

    exit_code = run.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Database backend: sqlite" in output
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
    monkeypatch.setenv("PGPASSWORD", "super-secret-password")
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
    assert "super-secret-password" not in captured.out
    assert "super-secret-password" not in captured.err


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
