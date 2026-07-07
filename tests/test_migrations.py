"""Regression tests for hand-written database migrations."""

import sqlite3

from flask import Flask

from musicround import db
from musicround.models import (
    ImportJobRecord,
    PlannedQuizRound,
    Round,
    RoundAudioScript,
    RoundExport,
    RoundShare,
    Song,
)


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


def _index_names(database_path, table_name):
    with sqlite3.connect(database_path) as conn:
        return [row[1] for row in conn.execute(f"PRAGMA index_list({table_name})").fetchall()]


def _table_names(database_path):
    with sqlite3.connect(database_path) as conn:
        return [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]


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


def test_add_query_performance_indexes_to_existing_tables(tmp_path):
    """Existing databases get indexes for catalog, queue, and scheduled-send reads."""
    database_path = tmp_path / "legacy-performance.db"
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            CREATE TABLE song (
                id INTEGER PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                artist VARCHAR(200) NOT NULL,
                genre VARCHAR(100),
                year INTEGER,
                preview_url VARCHAR(500),
                spotify_preview_url VARCHAR(500),
                deezer_preview_url VARCHAR(500),
                used_count INTEGER,
                last_used DATETIME
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE round (
                id INTEGER PRIMARY KEY,
                round_type VARCHAR(50) NOT NULL,
                round_criteria_used VARCHAR(500) NOT NULL,
                songs TEXT NOT NULL,
                created_at DATETIME,
                mp3_generated BOOLEAN,
                pdf_generated BOOLEAN
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE round_export (
                id INTEGER PRIMARY KEY,
                round_id INTEGER NOT NULL,
                export_type VARCHAR(20) NOT NULL,
                timestamp DATETIME,
                status VARCHAR(20),
                scheduled_for DATETIME
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE import_job_record (
                id INTEGER PRIMARY KEY,
                priority INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                status VARCHAR(20),
                created_at DATETIME
            )
            """
        )

    app = _legacy_app(database_path)
    with app.app_context():
        from migrations import add_query_performance_indexes

        assert add_query_performance_indexes.run_migration() is True
        assert add_query_performance_indexes.run_migration() is None

    assert "idx_song_artist_title" in _index_names(database_path, "song")
    assert "idx_song_genre_year" in _index_names(database_path, "song")
    assert "idx_song_usage" in _index_names(database_path, "song")
    assert "idx_round_generation_status" in _index_names(database_path, "round")
    assert "idx_round_export_schedule" in _index_names(database_path, "round_export")
    assert "idx_import_job_claim" in _index_names(database_path, "import_job_record")

    model_index_names = {
        index.name
        for table in (
            Song.__table__,
            Round.__table__,
            RoundExport.__table__,
            ImportJobRecord.__table__,
        )
        for index in table.indexes
    }
    assert "idx_song_artist_title" in model_index_names
    assert "idx_round_export_schedule" in model_index_names
    assert "idx_import_job_claim" in model_index_names


def test_add_round_collaboration_and_audio_scripts_to_legacy_database(tmp_path):
    """Legacy databases get round owner/share and audio-script review schema."""
    database_path = tmp_path / "legacy-round-collaboration.db"
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            CREATE TABLE round (
                id INTEGER PRIMARY KEY,
                round_type VARCHAR(50) NOT NULL,
                round_criteria_used VARCHAR(500) NOT NULL,
                songs TEXT NOT NULL,
                created_at DATETIME
            )
            """
        )

    app = _legacy_app(database_path)
    with app.app_context():
        from migrations import add_round_collaboration_and_audio_scripts

        assert add_round_collaboration_and_audio_scripts.run_migration() is True
        assert add_round_collaboration_and_audio_scripts.run_migration() is None

    round_columns = set(_column_names(database_path, "round"))
    assert {"user_id", "visibility"}.issubset(round_columns)
    assert "idx_round_owner_created" in _index_names(database_path, "round")
    assert "round_share" in _table_names(database_path)
    assert "round_audio_script" in _table_names(database_path)
    assert "idx_round_share_user" in _index_names(database_path, "round_share")
    assert "idx_round_audio_script_round_status" in _index_names(
        database_path, "round_audio_script"
    )
    assert "idx_round_audio_script_cue" in _index_names(
        database_path, "round_audio_script"
    )
    assert "cue_position" in _column_names(database_path, "round_audio_script")
    assert "user_id" in Round.__table__.columns.keys()
    assert RoundShare.__tablename__ == "round_share"
    assert RoundAudioScript.__tablename__ == "round_audio_script"
    assert "cue_position" in RoundAudioScript.__table__.columns.keys()


def test_add_round_review_workflow_to_legacy_database(tmp_path):
    """Legacy round tables get human review and approval columns."""
    database_path = tmp_path / "legacy-round-review.db"
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            CREATE TABLE round (
                id INTEGER PRIMARY KEY,
                round_type VARCHAR(50) NOT NULL,
                round_criteria_used VARCHAR(500) NOT NULL,
                songs TEXT NOT NULL,
                created_at DATETIME
            )
            """
        )

    app = _legacy_app(database_path)
    with app.app_context():
        from migrations import add_round_review_workflow

        assert add_round_review_workflow.run_migration() is True
        assert add_round_review_workflow.run_migration() is None

    round_columns = set(_column_names(database_path, "round"))
    assert {
        "review_status",
        "review_notes",
        "approved_at",
        "approved_by_id",
    }.issubset(round_columns)
    assert "idx_round_review_status" in _index_names(database_path, "round")
    assert "review_status" in Round.__table__.columns.keys()


def test_add_planned_quiz_rounds_to_legacy_database(tmp_path):
    """Existing databases get planned quiz production-board schema."""
    database_path = tmp_path / "legacy-planned-quiz.db"
    app = _legacy_app(database_path)
    with app.app_context():
        db.create_all()
        db.session.remove()
        db.drop_all()

        from migrations import add_planned_quiz_rounds

        assert add_planned_quiz_rounds.run_migration() is True
        assert add_planned_quiz_rounds.run_migration() is None

    assert "planned_quiz_round" in _table_names(database_path)
    columns = set(_column_names(database_path, "planned_quiz_round"))
    assert {
        "quiz_date",
        "quizmaster_id",
        "theme",
        "brief",
        "source_playlist_url",
        "due_at",
        "status",
        "round_id",
        "export_id",
    }.issubset(columns)
    assert "idx_planned_quiz_round_status_due" in _index_names(database_path, "planned_quiz_round")
    assert "idx_planned_quiz_round_quizmaster_date" in _index_names(
        database_path,
        "planned_quiz_round",
    )
    assert PlannedQuizRound.__tablename__ == "planned_quiz_round"


def test_round_songs_comment_matches_storage_behavior():
    """Round.songs remains documented and parsed as comma-separated IDs."""
    round_ = Round(
        round_type="manual",
        round_criteria_used="test",
        songs="1, 2,not-an-id,3",
    )

    assert round_.song_id_list == [1, 2, 3]
