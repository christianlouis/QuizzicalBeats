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
    output = capsys.readouterr().out
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
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["dry_run"] is True
    assert payload["candidate_count"] == 0
    assert "secret" not in output.lower()


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
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["dry_run"] is True
    assert payload["configured"] is True
    assert payload["sent"] is False
    assert payload["recipient"] == "admin@example.test"
    assert "secret" not in output.lower()


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
    assert payload["summary"]["actionable_count"] == 0
    assert "secret" not in output.lower()


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
                        title=f"Test Song" if index == 0 else f"Test Song {index + 1}",
                        artist="Test Artist",
                    )
                )
    engine.dispose()


def _table_payload(payload, table_name):
    return next(table for table in payload["tables"] if table["table"] == table_name)
