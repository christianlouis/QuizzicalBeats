"""Regression tests for hand-written database migrations."""

import sqlite3

from flask import Flask

from musicround import db
from musicround.models import ImportJobRecord, Round, Song


def _legacy_app(database_path):
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SECRET_KEY="test-secret-key-for-testing-only",
        AUTOMATION_TOKEN="test-automation-token-for-testing",
    )
    db.init_app(app)
    return app


def _column_names(database_path, table_name):
    with sqlite3.connect(database_path) as conn:
        return [column[1] for column in conn.execute(f"PRAGMA table_info({table_name})")]


def test_add_song_fields_adds_model_isrc_to_legacy_song_table(tmp_path):
    """Legacy databases upgraded by run_migration get Song.isrc."""
    database_path = tmp_path / "legacy-song.db"
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            CREATE TABLE song (
                id INTEGER PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                artist VARCHAR(200) NOT NULL
            )
            """
        )

    app = _legacy_app(database_path)
    with app.app_context():
        from migrations import add_song_fields

        assert add_song_fields.run_migration() is True

    columns = _column_names(database_path, "song")
    assert "isrc" in columns
    assert Song.__table__.columns["isrc"].type.length == 20

    with sqlite3.connect(database_path) as conn:
        indexes = [row[1] for row in conn.execute("PRAGMA index_list(song)").fetchall()]
    assert "ix_song_isrc" in indexes


def test_add_round_generation_status_adds_model_columns_to_legacy_round_table(tmp_path):
    """Legacy round tables get generated-asset status columns."""
    database_path = tmp_path / "legacy-round.db"
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            CREATE TABLE round (
                id INTEGER PRIMARY KEY,
                round_type VARCHAR(50) NOT NULL,
                round_criteria_used VARCHAR(500) NOT NULL,
                songs TEXT NOT NULL
            )
            """
        )

    app = _legacy_app(database_path)
    with app.app_context():
        from migrations import add_round_generation_status

        assert add_round_generation_status.run_migration() is True

    columns = set(_column_names(database_path, "round"))
    expected_columns = {"mp3_generated", "pdf_generated", "last_generated_at"}
    assert expected_columns.issubset(columns)
    assert expected_columns.issubset(Round.__table__.columns.keys())


def test_add_import_job_attempts_adds_retry_columns_to_legacy_table(tmp_path):
    """Legacy import-job tables get retry attempt tracking columns."""
    database_path = tmp_path / "legacy-import-jobs.db"
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            CREATE TABLE import_job_record (
                id INTEGER PRIMARY KEY,
                service_name VARCHAR(50) NOT NULL,
                item_type VARCHAR(20) NOT NULL,
                item_id VARCHAR(255) NOT NULL,
                priority INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                status VARCHAR(20),
                error_message TEXT
            )
            """
        )

    app = _legacy_app(database_path)
    with app.app_context():
        from migrations import add_import_job_attempts

        assert add_import_job_attempts.run_migration() is True

    columns = set(_column_names(database_path, "import_job_record"))
    expected_columns = {"attempt_count", "max_attempts"}
    assert expected_columns.issubset(columns)
    assert expected_columns.issubset(ImportJobRecord.__table__.columns.keys())


def test_round_songs_comment_matches_storage_behavior():
    """Round.songs remains documented and parsed as comma-separated IDs."""
    round_ = Round(
        round_type="manual",
        round_criteria_used="test",
        songs="1, 2,not-an-id,3",
    )

    assert round_.song_id_list == [1, 2, 3]
