"""Regression tests for hand-written database migrations."""

import sqlite3

import sqlalchemy as sa
from flask import Flask

from musicround import db
from musicround.models import (
    ImportJobRecord,
    PlannedQuizRound,
    Round,
    RoundAccessEvent,
    RoundAudioScript,
    RoundExport,
    RoundShare,
    SeedSource,
    SeedSourceRun,
    Song,
    UserPreferences,
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


def _foreign_keys(database_path, table_name):
    with sqlite3.connect(database_path) as conn:
        return conn.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()


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


def test_song_deezer_id_uses_big_integer_for_large_catalog_ids(tmp_path):
    """Deezer catalog ids can exceed PostgreSQL INTEGER range."""
    assert isinstance(Song.__table__.columns["deezer_id"].type, sa.BigInteger)

    database_path = tmp_path / "legacy-song.db"
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            CREATE TABLE song (
                id INTEGER PRIMARY KEY,
                deezer_id INTEGER,
                title VARCHAR(200) NOT NULL,
                artist VARCHAR(200) NOT NULL
            )
            """
        )

    app = _legacy_app(database_path)
    with app.app_context():
        from migrations import widen_song_deezer_id

        assert widen_song_deezer_id.run_migration() is None


def test_song_source_accepts_curated_import_labels(tmp_path):
    """Curated seed labels can be longer than the old 20-character source field."""
    assert Song.__table__.columns["source"].type.length == 50

    database_path = tmp_path / "legacy-song.db"
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            CREATE TABLE song (
                id INTEGER PRIMARY KEY,
                source VARCHAR(20),
                title VARCHAR(200) NOT NULL,
                artist VARCHAR(200) NOT NULL
            )
            """
        )

    app = _legacy_app(database_path)
    with app.app_context():
        from migrations import widen_song_source

        assert widen_song_source.run_migration() is None


def test_add_spotify_oauth_columns_adds_index_without_sqlite_master_query(tmp_path):
    """Spotify OAuth migration uses SQLAlchemy inspector instead of sqlite_master SQL."""
    database_path = tmp_path / "legacy-spotify-oauth.db"
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            CREATE TABLE user (
                id INTEGER PRIMARY KEY,
                username VARCHAR(80) NOT NULL,
                email VARCHAR(120) NOT NULL,
                password_hash VARCHAR(128)
            )
            """
        )

    app = _legacy_app(database_path)
    with app.app_context():
        from migrations import add_spotify_oauth_columns

        assert add_spotify_oauth_columns.run_migration() is True

    columns = set(_column_names(database_path, "user"))
    assert {
        "spotify_id",
        "spotify_token",
        "spotify_refresh_token",
        "spotify_token_expiry",
    }.issubset(columns)
    assert "idx_user_spotify_id" in _index_names(database_path, "user")


def test_ensure_oauth_provider_unique_indexes_normalizes_blank_values(tmp_path):
    """Provider uniqueness migration quotes the user table and handles blanks."""
    database_path = tmp_path / "legacy-oauth-indexes.db"
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            CREATE TABLE user (
                id INTEGER PRIMARY KEY,
                google_id VARCHAR(100),
                authentik_id VARCHAR(100),
                dropbox_id VARCHAR(100)
            )
            """
        )
        conn.execute(
            "INSERT INTO user (id, google_id, authentik_id, dropbox_id) "
            "VALUES (1, '', 'auth-a', NULL)"
        )
        conn.execute(
            "INSERT INTO user (id, google_id, authentik_id, dropbox_id) "
            "VALUES (2, 'google-a', '', 'dropbox-a')"
        )

    app = _legacy_app(database_path)
    with app.app_context():
        from migrations import ensure_oauth_provider_unique_indexes

        assert ensure_oauth_provider_unique_indexes.run_migration() is True

    indexes = set(_index_names(database_path, "user"))
    assert {
        "idx_user_google_id",
        "idx_user_authentik_id",
        "idx_user_dropbox_id",
    }.issubset(indexes)
    with sqlite3.connect(database_path) as conn:
        blank_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM user
            WHERE google_id = '' OR authentik_id = '' OR dropbox_id = ''
            """
        ).fetchone()[0]
    assert blank_count == 0


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


def test_add_import_job_result_metadata_adds_structured_metadata_column(tmp_path):
    """Legacy import queues get structured result metadata for repair hints."""
    database_path = tmp_path / "legacy-import-result-metadata.db"
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            CREATE TABLE import_job_record (
                id INTEGER PRIMARY KEY,
                service_name VARCHAR(50) NOT NULL,
                item_type VARCHAR(20) NOT NULL,
                item_id VARCHAR(255) NOT NULL,
                priority INTEGER NOT NULL DEFAULT 10,
                user_id INTEGER NOT NULL,
                status VARCHAR(20),
                created_at DATETIME,
                started_at DATETIME,
                completed_at DATETIME,
                error_message TEXT,
                imported_count INTEGER,
                skipped_count INTEGER,
                attempt_count INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3
            )
            """
        )

    app = _legacy_app(database_path)
    with app.app_context():
        from migrations import add_import_job_result_metadata

        assert add_import_job_result_metadata.run_migration() is True
        assert add_import_job_result_metadata.run_migration() is None

    columns = set(_column_names(database_path, "import_job_record"))
    assert "result_metadata" in columns
    assert "result_metadata" in ImportJobRecord.__table__.columns.keys()


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
    assert {
        "user_id",
        "visibility",
        "public_token",
        "public_token_created_at",
    }.issubset(round_columns)
    assert "idx_round_owner_created" in _index_names(database_path, "round")
    assert "idx_round_public_token" in _index_names(database_path, "round")
    assert "round_share" in _table_names(database_path)
    assert "round_access_event" in _table_names(database_path)
    assert "round_audio_script" in _table_names(database_path)
    assert "idx_round_share_user" in _index_names(database_path, "round_share")
    assert "idx_round_access_event_round_created" in _index_names(
        database_path, "round_access_event"
    )
    assert "idx_round_access_event_actor" in _index_names(
        database_path, "round_access_event"
    )
    assert "idx_round_access_event_target" in _index_names(
        database_path, "round_access_event"
    )
    assert "idx_round_audio_script_round_status" in _index_names(
        database_path, "round_audio_script"
    )
    assert "idx_round_audio_script_cue" in _index_names(
        database_path, "round_audio_script"
    )
    assert "cue_position" in _column_names(database_path, "round_audio_script")
    with sqlite3.connect(database_path) as conn:
        access_event_columns = {
            column[1]: column
            for column in conn.execute("PRAGMA table_info(round_access_event)")
        }
    created_at_column = access_event_columns["created_at"]
    assert created_at_column[3] == 1
    assert created_at_column[4] == "CURRENT_TIMESTAMP"
    access_event_foreign_keys = _foreign_keys(database_path, "round_access_event")
    assert ("round", "round_id", "id", "CASCADE") in {
        (row[2], row[3], row[4], row[6]) for row in access_event_foreign_keys
    }
    assert ("user", "actor_user_id", "id", "SET NULL") in {
        (row[2], row[3], row[4], row[6]) for row in access_event_foreign_keys
    }
    assert ("user", "target_user_id", "id", "SET NULL") in {
        (row[2], row[3], row[4], row[6]) for row in access_event_foreign_keys
    }
    assert "user_id" in Round.__table__.columns.keys()
    assert "public_token" in Round.__table__.columns.keys()
    assert Round.__table__.columns["public_token"].unique is not True
    assert any(
        index.name == "idx_round_public_token" and index.unique
        for index in Round.__table__.indexes
    )
    assert RoundShare.__tablename__ == "round_share"
    assert RoundAccessEvent.__tablename__ == "round_access_event"
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


def test_add_seed_source_registry_to_legacy_database(tmp_path):
    """Legacy databases get seed source registry and run-status tables."""
    database_path = tmp_path / "legacy-seed-source.db"
    app = _legacy_app(database_path)
    with app.app_context():
        from migrations import add_seed_source_registry

        assert add_seed_source_registry.run_migration() is True
        assert add_seed_source_registry.run_migration() is None

    assert "seed_source" in _table_names(database_path)
    assert "seed_source_run" in _table_names(database_path)
    assert "idx_seed_source_type_active" in _index_names(database_path, "seed_source")
    assert "idx_seed_source_run_source_status" in _index_names(
        database_path, "seed_source_run"
    )
    assert "notes" in _column_names(database_path, "seed_source")
    assert any(
        row[2] == "seed_source" and row[3] == "seed_source_id" and row[4] == "id"
        for row in _foreign_keys(database_path, "seed_source_run")
    )
    assert SeedSource.__tablename__ == "seed_source"
    assert SeedSourceRun.__tablename__ == "seed_source_run"
    assert "idx_seed_source_type_active" in {
        index.name for index in SeedSource.__table__.indexes
    }
    assert "idx_seed_source_run_source_status" in {
        index.name for index in SeedSourceRun.__table__.indexes
    }


def test_add_seed_source_registry_rebuilds_existing_run_table_with_foreign_key(tmp_path):
    """Legacy seed source run tables without constraints are rebuilt safely."""
    database_path = tmp_path / "legacy-seed-source-run-no-fk.db"
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            CREATE TABLE seed_source (
                id INTEGER PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                source_type VARCHAR(50) NOT NULL,
                provider VARCHAR(100),
                url VARCHAR(500),
                cadence VARCHAR(50),
                active BOOLEAN NOT NULL DEFAULT 1,
                priority INTEGER NOT NULL DEFAULT 100,
                created_at DATETIME NOT NULL,
                UNIQUE(name, provider)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE seed_source_run (
                id INTEGER PRIMARY KEY,
                seed_source_id INTEGER NOT NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'planned',
                started_at DATETIME NOT NULL,
                completed_at DATETIME,
                songs_seen INTEGER NOT NULL DEFAULT 0,
                songs_imported INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                notes TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO seed_source (id, name, source_type, created_at) "
            "VALUES (1, 'Charts', 'chart', '2026-07-07')"
        )
        conn.execute(
            "INSERT INTO seed_source_run (id, seed_source_id, status, started_at) "
            "VALUES (10, 1, 'success', '2026-07-07')"
        )
        conn.execute(
            "INSERT INTO seed_source_run (id, seed_source_id, status, started_at) "
            "VALUES (11, 999, 'orphan', '2026-07-07')"
        )

    app = _legacy_app(database_path)
    with app.app_context():
        from migrations import add_seed_source_registry

        assert add_seed_source_registry.run_migration() is True
        assert add_seed_source_registry.run_migration() is None

    assert any(
        row[2] == "seed_source" and row[3] == "seed_source_id" and row[4] == "id"
        for row in _foreign_keys(database_path, "seed_source_run")
    )
    with sqlite3.connect(database_path) as conn:
        rows = conn.execute("SELECT id, seed_source_id, status FROM seed_source_run").fetchall()
    assert rows == [(10, 1, "success")]


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


def test_add_quizmaster_profile_preferences_to_legacy_database(tmp_path):
    """Existing user preferences get quizmaster profile columns."""
    database_path = tmp_path / "legacy-quizmaster-profile.db"
    app = _legacy_app(database_path)
    with app.app_context():
        db.create_all()
        db.session.remove()
        db.drop_all()
        with sqlite3.connect(database_path) as conn:
            conn.execute(
                """
                CREATE TABLE user_preferences (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER UNIQUE,
                    default_tts_service VARCHAR(32),
                    enable_intro BOOLEAN,
                    theme VARCHAR(16)
                )
                """
            )
            conn.execute(
                "INSERT INTO user_preferences "
                "(id, user_id, default_tts_service, enable_intro, theme) "
                "VALUES (1, 10, 'polly', 1, 'light')"
            )

        from migrations import add_quizmaster_profile_preferences

        assert add_quizmaster_profile_preferences.run_migration() is True
        assert add_quizmaster_profile_preferences.run_migration() is None

    columns = set(_column_names(database_path, "user_preferences"))
    assert {
        "default_language",
        "tone",
        "tts_voice",
        "email_recipient",
        "preferred_genres",
        "preferred_decades",
        "banned_artists",
        "banned_songs",
        "repeat_cooldown_weeks",
    }.issubset(columns)
    with sqlite3.connect(database_path) as conn:
        row = conn.execute(
            "SELECT default_language, tone, repeat_cooldown_weeks "
            "FROM user_preferences WHERE id = 1"
        ).fetchone()
    assert row[0] == "de"
    assert row[1] == "warm, concise, lightly humorous"
    assert row[2] == 12
    assert "default_language" in UserPreferences.__table__.columns.keys()


def test_round_songs_comment_matches_storage_behavior():
    """Round.songs remains documented and parsed as comma-separated IDs."""
    round_ = Round(
        round_type="manual",
        round_criteria_used="test",
        songs="1, 2,not-an-id,3",
    )

    assert round_.song_id_list == [1, 2, 3]
