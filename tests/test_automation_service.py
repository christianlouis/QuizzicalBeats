"""Tests for agent automation services."""

import os
import json
import shutil
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from pydub import AudioSegment

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only")
os.environ.setdefault("AUTOMATION_TOKEN", "test-automation-token-for-testing")

from musicround.helpers.import_queue import ImportQueue
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
    SongTag,
    SystemSetting,
    Tag,
    User,
    UserPreferences,
    db,
)
from musicround.services import automation


def _create_user(username="agentuser", email="agent@example.com"):
    user = User(username=username, email=email)
    user.password = "AgentPass123!"
    db.session.add(user)
    db.session.commit()
    return user


def _create_song(title="Song", artist="Artist", **kwargs):
    song = Song(title=title, artist=artist, **kwargs)
    db.session.add(song)
    db.session.commit()
    return song


def _configure_mail(app):
    app.config.update(
        MAIL_HOST="smtp.example.test",
        MAIL_PORT=587,
        MAIL_USERNAME="mailer",
        MAIL_PASSWORD="secret",
        MAIL_SENDER="sender@example.test",
    )


def _future_schedule_pair(days=7):
    scheduled_at = (datetime.utcnow() + timedelta(days=days)).replace(microsecond=0)
    due_at = scheduled_at + timedelta(minutes=1)
    return f"{scheduled_at.isoformat()}Z", f"{due_at.isoformat()}Z", scheduled_at


def _approve_round(round_id, reviewer=None):
    round_obj = db.session.get(Round, round_id)
    round_obj.review_status = "approved"
    round_obj.approved_at = datetime.utcnow()
    round_obj.approved_by_id = reviewer.id if reviewer else None
    db.session.commit()
    return round_obj


class TestSongAutomation:
    """Tests for catalog lookup and mutation."""

    def test_find_songs_by_query(self, app):
        with app.app_context():
            _create_song(
                title="Blue Monday",
                artist="New Order",
                genre="Synthpop",
                deezer_preview_url="https://example.test/blue.mp3",
                used_count=3,
            )

            result = automation.find_songs(query="blue")

            assert result["count"] == 1
            assert result["songs"][0]["title"] == "Blue Monday"
            assert result["songs"][0]["preview_url"] == "https://example.test/blue.mp3"
            assert result["songs"][0]["used_count"] == 3
            assert result["songs"][0]["usage_frequency"] == 3
            assert "last_used" in result["songs"][0]

    def test_find_songs_filters_catalog_for_agent_selection(self, app):
        with app.app_context():
            _create_song(
                title="Filtered Rock 1999",
                artist="Alpha",
                genre="Rock",
                year=1999,
                preview_url="https://example.test/alpha.mp3",
                used_count=0,
            )
            _create_song(
                title="Filtered Rock 2001",
                artist="Beta",
                genre="Rock",
                year=2001,
                preview_url="https://example.test/beta.mp3",
                used_count=0,
            )
            _create_song(
                title="Filtered Pop 1998",
                artist="Gamma",
                genre="Pop",
                year=1998,
                used_count=2,
            )

            result = automation.find_songs(
                query="Filtered",
                genre="Rock",
                year_min=1990,
                year_max=2000,
                has_preview=True,
                unused_only=True,
                order_by="-year",
                limit=10,
            )

            assert result["count"] == 1
            assert result["total"] == 1
            assert result["filters"]["genre"] == "Rock"
            assert result["filters"]["has_preview"] is True
            assert result["filters"]["unused_only"] is True
            assert result["songs"][0]["title"] == "Filtered Rock 1999"

    def test_find_songs_rejects_invalid_pagination_and_sort(self, app):
        with app.app_context():
            with pytest.raises(automation.AutomationError, match="offset"):
                automation.find_songs(offset=-1)

            with pytest.raises(automation.AutomationError, match="order_by"):
                automation.find_songs(order_by="popularity")

    def test_add_song_reuses_existing_by_isrc_and_adds_tags(self, app):
        with app.app_context():
            _create_song(title="Old Title", artist="Old Artist", isrc="ABC123")

            result = automation.add_song(
                title="New Title",
                artist="New Artist",
                isrc="ABC123",
                tags=["warmup", "classic"],
            )

            assert result["created"] is False
            assert Song.query.count() == 1
            song = Song.query.first()
            assert song.title == "New Title"
            assert sorted(tag.name for tag in song.tags) == ["classic", "warmup"]


class TestRoundAutomation:
    """Tests for round creation and naming."""

    def test_create_round_assigns_owner_and_visibility(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="Owned", artist="A")

            created = automation.create_round(
                name="Owned Round",
                round_type="manual",
                song_ids=[song.id],
                user_id=user.id,
                visibility="private",
            )

            round_obj = db.session.get(Round, created["round"]["id"])
            assert created["round"]["owner_user_id"] == user.id
            assert created["round"]["owner"]["username"] == user.username
            assert round_obj.owner.id == user.id
            assert round_obj.visibility == "private"

    def test_create_and_rename_manual_round(self, app):
        with app.app_context():
            song_one = _create_song(title="One", artist="A")
            song_two = _create_song(title="Two", artist="B")

            created = automation.create_round(
                name="Initial Name",
                round_type="manual",
                song_ids=[song_one.id, song_two.id],
            )
            renamed = automation.rename_round(created["round"]["id"], "Final Name")

            assert created["round"]["song_ids"] == [song_one.id, song_two.id]
            assert renamed["round"]["name"] == "Final Name"
            assert Song.query.get(song_one.id).used_count == 1

    def test_create_round_from_playlist_fails_when_too_few_tracks_resolve(self, app):
        with app.app_context():
            song = _create_song(title="Only Resolved", artist="A")

            with (
                patch(
                    "musicround.services.automation.import_catalog_item",
                    return_value={"item_id": "playlist123", "result": {}},
                ),
                patch(
                    "musicround.services.automation._spotify_playlist_song_ids",
                    return_value=[song.id],
                ),
            ):
                with pytest.raises(automation.AutomationError) as exc_info:
                    automation.create_round_from_playlist(
                        "spotify",
                        "playlist123",
                        count=8,
                    )

            assert exc_info.value.details["status"] == "needs_more_songs"
            assert exc_info.value.details["expected_song_count"] == 8
            assert exc_info.value.details["resolved_song_count"] == 1
            assert exc_info.value.details["resolved_positions"][0]["position"] == 1
            assert exc_info.value.details["resolved_positions"][0]["song_id"] == song.id
            assert exc_info.value.details["resolved_positions"][0]["resolved"] is True
            assert exc_info.value.details["resolved_positions"][1]["reason"] == "not_resolved"
            assert exc_info.value.details["missing_positions"] == [2, 3, 4, 5, 6, 7, 8]

    def test_create_round_from_playlist_returns_resolved_position_map(self, app):
        with app.app_context():
            first_song = _create_song(title="First", artist="A")
            second_song = _create_song(title="Second", artist="B")

            with (
                patch(
                    "musicround.services.automation.import_catalog_item",
                    return_value={
                        "item_id": "playlist123",
                        "result": {
                            "playlist_positions": [
                                {
                                    "position": 1,
                                    "spotify_track_id": "spotify-first",
                                    "artist": "A",
                                    "title": "First",
                                    "song_id": first_song.id,
                                    "status": "resolved",
                                    "reason": None,
                                },
                                {
                                    "position": 2,
                                    "spotify_track_id": "spotify-second",
                                    "artist": "B",
                                    "title": "Second",
                                    "song_id": second_song.id,
                                    "status": "resolved",
                                    "reason": None,
                                },
                            ],
                        },
                    },
                ),
                patch(
                    "musicround.services.automation._spotify_playlist_song_ids",
                    return_value=[first_song.id, second_song.id],
                ),
            ):
                result = automation.create_round_from_playlist(
                    "spotify",
                    "playlist123",
                    count=2,
                )

            assert result["round"]["song_ids"] == [first_song.id, second_song.id]
            assert result["resolved_positions"][0] == {
                "position": 1,
                "song_id": first_song.id,
                "resolved": True,
                "status": "resolved",
                "spotify_track_id": "spotify-first",
                "artist": "A",
                "title": "First",
                "reason": None,
            }
            assert result["resolved_positions"][1]["spotify_track_id"] == "spotify-second"

    def test_create_round_from_playlist_preserves_failed_source_positions(self, app):
        with app.app_context():
            first_song = _create_song(title="First", artist="A")
            third_song = _create_song(title="Third", artist="C")

            with (
                patch(
                    "musicround.services.automation.import_catalog_item",
                    return_value={
                        "item_id": "playlist123",
                        "result": {
                            "playlist_positions": [
                                {
                                    "position": 1,
                                    "spotify_track_id": "spotify-first",
                                    "artist": "A",
                                    "title": "First",
                                    "song_id": first_song.id,
                                    "status": "resolved",
                                    "reason": None,
                                },
                                {
                                    "position": 2,
                                    "spotify_track_id": None,
                                    "artist": "B",
                                    "title": "Broken",
                                    "song_id": None,
                                    "status": "failed",
                                    "reason": "missing_spotify_track_id",
                                },
                                {
                                    "position": 3,
                                    "spotify_track_id": "spotify-third",
                                    "artist": "C",
                                    "title": "Third",
                                    "song_id": third_song.id,
                                    "status": "resolved",
                                    "reason": None,
                                },
                            ],
                        },
                    },
                ),
                patch("musicround.services.automation._spotify_playlist_song_ids") as mock_song_ids,
            ):
                with pytest.raises(automation.AutomationError) as exc_info:
                    automation.create_round_from_playlist(
                        "spotify",
                        "playlist123",
                        count=3,
                    )

            mock_song_ids.assert_not_called()
            assert exc_info.value.details["resolved_song_count"] == 2
            assert exc_info.value.details["missing_positions"] == [2]
            assert exc_info.value.details["resolved_positions"][1] == {
                "position": 2,
                "song_id": None,
                "resolved": False,
                "status": "failed",
                "spotify_track_id": None,
                "artist": "B",
                "title": "Broken",
                "reason": "missing_spotify_track_id",
            }
            assert Round.query.count() == 0

    def test_replace_round_song_updates_position_and_invalidates_assets(self, app):
        with app.app_context():
            song_one = _create_song(title="One", artist="A")
            song_two = _create_song(title="Two", artist="B")
            replacement = _create_song(title="Replacement", artist="C")
            round_id = automation.create_round(
                name="Repair Me",
                round_type="manual",
                song_ids=[song_one.id, song_two.id],
            )["round"]["id"]
            round_obj = db.session.get(Round, round_id)
            round_obj.mp3_generated = True
            round_obj.pdf_generated = True
            db.session.commit()

            result = automation.replace_round_song(
                round_id,
                position=2,
                replacement_song_id=replacement.id,
            )

            assert result["position"] == 2
            assert result["replaced_song"]["id"] == song_two.id
            assert result["replacement_song"]["id"] == replacement.id
            assert result["round"]["song_ids"] == [song_one.id, replacement.id]
            refreshed_round = db.session.get(Round, round_id)
            assert refreshed_round.mp3_generated is False
            assert refreshed_round.pdf_generated is False
            assert Song.query.get(song_two.id).used_count == 0
            assert Song.query.get(replacement.id).used_count == 1

    def test_add_round_song_appends_and_invalidates_assets(self, app):
        with app.app_context():
            song_one = _create_song(title="One", artist="A")
            addition = _create_song(title="Addition", artist="B")
            round_id = automation.create_round(
                name="Needs One",
                round_type="manual",
                song_ids=[song_one.id],
            )["round"]["id"]
            round_obj = db.session.get(Round, round_id)
            round_obj.mp3_generated = True
            round_obj.pdf_generated = True
            db.session.commit()

            result = automation.add_round_song(round_id, addition.id)

            assert result["position"] == 2
            assert result["added_song"]["id"] == addition.id
            assert result["round"]["song_ids"] == [song_one.id, addition.id]
            refreshed_round = db.session.get(Round, round_id)
            assert refreshed_round.mp3_generated is False
            assert refreshed_round.pdf_generated is False
            assert Song.query.get(addition.id).used_count == 1

    def test_add_round_song_rejects_duplicate_song(self, app):
        with app.app_context():
            song = _create_song(title="One", artist="A")
            round_id = automation.create_round(
                name="Duplicate",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]

            with pytest.raises(automation.AutomationError, match="already in round"):
                automation.add_round_song(round_id, song.id)

    def test_suggest_replacement_songs_prefers_similar_unused_candidates(self, app):
        with app.app_context():
            original = _create_song(
                title="Broken",
                artist="A",
                genre="Rock",
                year=1990,
                deezer_id=100,
            )
            in_round = _create_song(
                title="Already In Round",
                artist="B",
                genre="Rock",
                year=1991,
                deezer_id=101,
            )
            best = _create_song(
                title="Best",
                artist="C",
                genre="Rock",
                year=1992,
                deezer_id=102,
            )
            _create_song(
                title="Different",
                artist="D",
                genre="Pop",
                year=2010,
                deezer_id=103,
            )
            round_id = automation.create_round(
                name="Needs Candidate",
                round_type="manual",
                song_ids=[original.id, in_round.id],
            )["round"]["id"]

            result = automation.suggest_replacement_songs(
                round_id,
                position=1,
                limit=3,
            )

            suggestion_ids = [song["id"] for song in result["suggestions"]]
            assert best.id == suggestion_ids[0]
            assert original.id not in suggestion_ids
            assert in_round.id not in suggestion_ids
            assert result["suggestions"][0]["same_genre"] is True

    def test_suggest_replacement_songs_accepts_song_id_and_returns_agent_fields(self, app):
        with app.app_context():
            original = _create_song(
                title="Overplayed",
                artist="Known Artist",
                genre="Country",
                year=1998,
                deezer_id=110,
                used_count=7,
            )
            best = _create_song(
                title="Fresh Country Hook",
                artist="New Artist",
                genre="Country",
                year=1999,
                deezer_id=111,
                spotify_id="spotify-best",
                isrc="TESTISRC1",
                preview_url="https://example.test/best.mp3",
            )
            weaker = _create_song(
                title="Fresh Pop Hook",
                artist="Pop Artist",
                genre="Pop",
                year=2010,
                deezer_id=112,
                preview_url="https://example.test/weaker.mp3",
            )

            result = automation.suggest_replacement_songs(
                song_id=original.id,
                theme="country hook",
                preferred_decade="1990s",
                prefer_same_decade=True,
                limit=2,
            )

            assert result["round_id"] is None
            assert result["original_song"]["id"] == original.id
            assert [song["id"] for song in result["suggestions"]] == [best.id, weaker.id]
            first = result["suggestions"][0]
            assert first["platform_ids"] == {
                "spotify": "spotify-best",
                "deezer": best.deezer_id,
                "isrc": "TESTISRC1",
            }
            assert first["preview"]["available"] is True
            assert first["preview"]["duration_seconds"] is None
            assert first["usage_history"]["used_count"] == 0
            assert first["constraint_matches"]["same_decade"] is True
            assert any("catalog preview" in reason for reason in first["explanation"])

    def test_suggest_replacement_songs_accepts_artist_title_theme_and_constraints(self, app):
        with app.app_context():
            original = _create_song(
                title="Broken Anthem",
                artist="Reference Band",
                genre="Rock",
                year=2004,
                deezer_id=120,
            )
            avoid = _create_song(
                title="Avoid This Anthem",
                artist="Reference Band",
                genre="Rock",
                year=2004,
                deezer_id=121,
                preview_url="https://example.test/avoid.mp3",
            )
            candidate = _create_song(
                title="Festival Anthem",
                artist="Other Band",
                genre="Rock",
                year=2005,
                deezer_id=122,
                preview_url="https://example.test/candidate.mp3",
            )
            tag = Tag(name="festival")
            candidate.tags.append(tag)
            db.session.add(tag)
            db.session.commit()

            result = automation.suggest_replacement_songs(
                artist="Reference Band",
                title="Broken Anthem",
                theme="festival anthem",
                preferred_mood="festival",
                constraints={"avoid": ["Avoid This"]},
                limit=2,
            )

            suggestion_ids = [song["id"] for song in result["suggestions"]]
            assert original.id not in suggestion_ids
            assert candidate.id == suggestion_ids[0]
            assert avoid.id == suggestion_ids[1]
            assert result["suggestions"][0]["constraint_matches"]["mood"] is True
            assert result["suggestions"][1]["constraint_matches"]["avoid"] is True

    def test_suggest_replacement_songs_validates_position_and_preview_inputs(self, app):
        with app.app_context():
            with pytest.raises(automation.AutomationError, match="position"):
                automation.suggest_replacement_songs(position=1)

            with pytest.raises(automation.AutomationError, match="min_preview_seconds"):
                automation.suggest_replacement_songs(query="anthem", min_preview_seconds=0)

            with pytest.raises(automation.AutomationError, match="min_preview_seconds"):
                automation.suggest_replacement_songs(query="anthem", min_preview_seconds=float("nan"))

            with pytest.raises(automation.AutomationError, match=r"constraints\.avoid"):
                automation.suggest_replacement_songs(
                    query="anthem",
                    constraints={"avoid": object()},
                )

            with pytest.raises(automation.AutomationError, match=r"constraints\.avoid"):
                automation.suggest_replacement_songs(
                    query="anthem",
                    constraints={"avoid": {"artist": "A"}},
                )

    def test_suggest_replacement_songs_normalizes_text_inputs_and_filters(self, app):
        with app.app_context():
            _create_song(
                title="Fresh Anthem",
                artist="Catalog Band",
                genre="Rock",
                year=2001,
                deezer_id=130,
                preview_url="https://example.test/fresh.mp3",
            )

            result = automation.suggest_replacement_songs(
                query="  Fresh   Anthem  ",
                theme="  big   chorus  ",
                constraints={"avoid": "skip this"},
            )

            assert result["filters"]["query"] == "Fresh Anthem"
            assert result["filters"]["theme"] == "big chorus"
            assert result["filters"]["constraints"] == {"avoid": ["skip this"]}
            assert result["count"] == 1

            none_result = automation.suggest_replacement_songs(
                query="  Fresh   Anthem  ",
                constraints={"avoid": None},
            )

            assert none_result["filters"]["constraints"] == {"avoid": []}
            assert none_result["count"] == 1

    def test_suggest_additional_songs_excludes_current_round(self, app):
        with app.app_context():
            in_round = _create_song(title="Already In Round", artist="A", deezer_id=200)
            addition = _create_song(title="Possible", artist="B", deezer_id=201)
            _create_song(title="No Deezer", artist="C")
            round_id = automation.create_round(
                name="Needs More",
                round_type="manual",
                song_ids=[in_round.id],
            )["round"]["id"]

            result = automation.suggest_additional_songs(round_id, limit=5)

            suggestion_ids = [song["id"] for song in result["suggestions"]]
            assert addition.id in suggestion_ids
            assert in_round.id not in suggestion_ids

    def test_share_round_lifecycle(self, app):
        with app.app_context():
            owner = _create_user(username="owner", email="owner@example.test")
            viewer = _create_user(username="viewer", email="viewer@example.test")
            song = _create_song(title="Shared", artist="A")
            round_id = automation.create_round(
                name="Share Me",
                round_type="manual",
                song_ids=[song.id],
                user_id=owner.id,
            )["round"]["id"]

            shared = automation.share_round(round_id, viewer.id, role="editor", actor_user_id=owner.id)
            listed = automation.list_round_shares(round_id)
            events_after_share = automation.list_round_access_events(round_id)
            revoked = automation.revoke_round_share(round_id, viewer.id, actor_user_id=owner.id)
            events_after_revoke = automation.list_round_access_events(round_id)

            assert shared["created"] is True
            assert shared["share"]["role"] == "editor"
            assert shared["access_event"]["action"] == "share_created"
            assert shared["access_event"]["actor_user_id"] == owner.id
            assert shared["access_event"]["target_user_id"] == viewer.id
            assert listed["count"] == 1
            assert listed["owner"]["id"] == owner.id
            assert events_after_share["count"] == 1
            assert events_after_share["events"][0]["action"] == "share_created"
            assert revoked["revoked"] is True
            assert revoked["access_event"]["action"] == "share_revoked"
            assert events_after_revoke["count"] == 2
            assert events_after_revoke["events"][0]["action"] == "share_revoked"
            assert RoundShare.query.count() == 0
            assert RoundAccessEvent.query.count() == 2
            assert db.session.get(Round, round_id).visibility == "private"

            producer_share = automation.share_round(round_id, viewer.id, role="producer", actor_user_id=owner.id)

            assert producer_share["created"] is True
            assert producer_share["share"]["role"] == "producer"
            assert RoundAccessEvent.query.count() == 3
            assert db.session.get(Round, round_id).visibility == "shared"

    def test_share_round_rejects_invalid_actor_user_id(self, app):
        with app.app_context():
            owner = _create_user(username="owner", email="owner@example.test")
            viewer = _create_user(username="viewer", email="viewer@example.test")
            song = _create_song(title="Shared", artist="A")
            round_id = automation.create_round(
                name="Share Me",
                round_type="manual",
                song_ids=[song.id],
                user_id=owner.id,
            )["round"]["id"]

            with pytest.raises(automation.AutomationError, match="User 9999"):
                automation.share_round(round_id, viewer.id, actor_user_id=9999)

            automation.share_round(round_id, viewer.id, actor_user_id=owner.id)
            with pytest.raises(automation.AutomationError, match="User 9999"):
                automation.revoke_round_share(round_id, viewer.id, actor_user_id=9999)

            assert RoundAccessEvent.query.count() == 1

    def test_database_configuration_summary_warns_for_legacy_sqlite(self, app):
        """MCP database diagnostics should flag legacy SQLite without leaking paths."""
        with app.app_context():
            app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:////data/song_data.db"
            app.config["DATABASE_BACKEND"] = "sqlite"
            app.config["DATABASE_REQUIRE_MANAGED"] = False

            result = automation.database_configuration_summary()

        assert result["ok"] is True
        assert result["status"] == "warning"
        assert result["database"]["backend"] == "sqlite"
        assert result["database"]["redacted_uri"] == "sqlite:///[local-file]"
        assert result["issues"][0]["code"] == "legacy_sqlite_data_store"
        assert "/data/song_data.db" not in repr(result)

    def test_database_configuration_summary_is_credential_safe_for_pg_env(self, app, monkeypatch):
        """MCP database diagnostics should expose key names but not secret values."""
        monkeypatch.setenv("PGHOST", "postgres.internal")
        monkeypatch.setenv("PGDATABASE", "quizzicalbeats")
        monkeypatch.setenv("PGUSER", "qb_user")
        monkeypatch.setenv("PGPASSWORD", "super-secret-password")
        monkeypatch.setenv("PGSSLMODE", "require")
        with app.app_context():
            app.config["SQLALCHEMY_DATABASE_URI"] = (
                "postgresql://qb_user:super-secret-password@postgres.internal/quizzicalbeats"
            )
            app.config["DATABASE_BACKEND"] = "postgresql"
            app.config["DATABASE_REQUIRE_MANAGED"] = True

            result = automation.database_configuration_summary()

        assert result["ok"] is True
        assert result["status"] == "warning"
        assert result["managed_required"] is True
        assert result["database"]["backend"] == "postgresql"
        assert result["postgres_env"]["complete"] is True
        assert result["issues"][0]["code"] == "database_uri_overrides_postgres_env"
        assert result["postgres_env"]["present_required"] == [
            "PGHOST",
            "PGDATABASE",
            "PGUSER",
            "PGPASSWORD",
        ]
        serialized = repr(result)
        assert "super-secret-password" not in serialized
        assert "postgresql://qb_user:***@postgres.internal/quizzicalbeats" in serialized

    def test_database_cutover_plan_summary_blocks_legacy_sqlite(self, app):
        """MCP agents should get next safe cutover steps without raw paths."""
        with app.app_context():
            app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:////data/song_data.db"
            app.config["DATABASE_BACKEND"] = "sqlite"
            app.config["DATABASE_REQUIRE_MANAGED"] = False

            result = automation.database_cutover_plan_summary()

        assert result["ok"] is False
        assert result["status"] == "blocked"
        assert result["database"]["backend"] == "sqlite"
        assert "configure_managed_database" in result["blocked_steps"]
        assert "backup_legacy_sqlite" in result["ready_steps"]
        assert "/data/song_data.db" not in repr(result)

    def test_list_round_access_events_requires_owner_or_admin_requester(self, app):
        with app.app_context():
            owner = _create_user(username="owner", email="owner@example.test")
            viewer = _create_user(username="viewer", email="viewer@example.test")
            admin = _create_user(username="admin", email="admin@example.test")
            admin.is_admin = True
            song = _create_song(title="Shared", artist="A")
            round_id = automation.create_round(
                name="Share Me",
                round_type="manual",
                song_ids=[song.id],
                user_id=owner.id,
            )["round"]["id"]
            automation.share_round(round_id, viewer.id, actor_user_id=owner.id)

            owner_events = automation.list_round_access_events(round_id, requester_user_id=owner.id)
            admin_events = automation.list_round_access_events(round_id, requester_user_id=admin.id)
            with pytest.raises(automation.AutomationError, match="owner or an admin"):
                automation.list_round_access_events(round_id, requester_user_id=viewer.id)
            with pytest.raises(automation.AutomationError, match="limit must be an integer"):
                automation.list_round_access_events(round_id, limit="many", requester_user_id=owner.id)

            assert owner_events["count"] == 1
            assert admin_events["count"] == 1

    def test_round_public_link_lifecycle_requires_enabled_setting_and_manager(self, app):
        with app.app_context():
            owner = _create_user(username="owner", email="owner@example.test")
            viewer = _create_user(username="viewer", email="viewer@example.test")
            admin = _create_user(username="admin", email="admin@example.test")
            admin.is_admin = True
            song = _create_song(title="Public Song", artist="Artist", genre="Pop", year=1999)
            round_id = automation.create_round(
                name="Public Link Round",
                round_type="manual",
                song_ids=[song.id],
                user_id=owner.id,
            )["round"]["id"]

            with pytest.raises(automation.AutomationError, match="disabled"):
                automation.enable_round_public_link(round_id, actor_user_id=owner.id)

            SystemSetting.set("enable_public_rounds", "true")
            with pytest.raises(automation.AutomationError, match="owner or an admin"):
                automation.enable_round_public_link(round_id, actor_user_id=viewer.id)

            enabled = automation.enable_round_public_link(round_id, actor_user_id=owner.id)
            public = automation.get_public_round(enabled["public_token"])
            refreshed = automation.enable_round_public_link(round_id, actor_user_id=admin.id)
            disabled = automation.disable_round_public_link(round_id, actor_user_id=owner.id)

            assert enabled["created"] is True
            assert enabled["public_url_path"].startswith("/rounds/public/")
            assert enabled["round"]["public_link_enabled"] is True
            assert public["round"]["name"] == "Public Link Round"
            assert public["round"]["songs"][0]["title"] == "Public Song"
            assert public["round"]["owner"] == {
                "id": owner.id,
                "username": owner.username,
                "name": None,
            }
            assert "email" not in public["round"]["owner"]
            assert refreshed["created"] is False
            assert refreshed["public_token"] == enabled["public_token"]
            assert refreshed["access_event"]["action"] == "public_link_refreshed"
            assert disabled["disabled"] is True
            assert disabled["round"]["public_link_enabled"] is False
            with pytest.raises(automation.AutomationError, match="not found"):
                automation.get_public_round(enabled["public_token"])

            actions = [event.action for event in RoundAccessEvent.query.order_by(RoundAccessEvent.id).all()]
            assert actions == [
                "public_link_enabled",
                "public_link_refreshed",
                "public_link_disabled",
            ]


class TestAssetInspection:
    """Tests for generated asset quality checks."""

    def test_inspect_pdf_quality(self, app):
        with app.app_context(), tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(b"%PDF-1.4\n")
            tmp.write(b"1 0 obj << /Type /Page >> endobj\n" * 40)
            tmp.write(b"%%EOF")
            tmp_path = tmp.name

        try:
            with app.app_context():
                result = automation.inspect_pdf_quality(path=tmp_path)

            assert result["ok"] is True
            assert result["page_count_estimate"] > 0
        finally:
            os.remove(tmp_path)

    def test_inspect_mp3_quality_existing_fixture(self, app):
        if not shutil.which("ffprobe"):
            pytest.skip("ffprobe is required for MP3 inspection")

        fixture_path = os.path.abspath("musicround/mp3/intro.mp3")

        with app.app_context():
            result = automation.inspect_mp3_quality(path=fixture_path)

        assert result["duration_seconds"] > 0
        assert result["channels"] >= 1
        assert "ok" in result

    def test_inspect_round_package_requires_exact_song_count(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="Only One", artist="Artist", deezer_id="123")
            round_id = automation.create_round(
                name="Too Short",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]

            with (
                patch(
                    "musicround.services.automation._download_preview_audio",
                    return_value=("https://example.test/preview.mp3", AudioSegment.silent(duration=30000), None),
                ),
                patch(
                    "musicround.services.automation._round_audio_components",
                    return_value=(
                        {"custom_audio_ms": {"intro": 1000, "replay": 1000, "outro": 1000}, "number_audio_ms": [1000]},
                        [],
                    ),
                ),
                patch(
                    "musicround.services.automation.inspect_pdf_quality",
                    return_value={"warnings": [], "ok": True},
                ),
                patch(
                    "musicround.services.automation.inspect_mp3_quality",
                    return_value={"warnings": [], "ok": True, "duration_seconds": 65},
                ),
            ):
                result = automation.inspect_round_package(round_id, user_id=user.id)

            assert result["ok"] is False
            assert result["status"] == "needs_more_songs"
            assert result["expected_song_count"] == 8
            assert result["actual_song_count"] == 1
            assert any(
                issue["code"] == "actual_song_count_mismatch"
                for issue in result["issues"]
            )

    def test_inspect_round_package_reports_unhealthy_artifact_storage(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="Storage", artist="Artist", deezer_id="123")
            round_id = automation.create_round(
                name="Storage Bad",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]
            missing_dir = os.path.join(app.instance_path, "missing-artifacts")
            app.config["ROUND_MP3_DIR"] = missing_dir

            with (
                patch(
                    "musicround.services.automation._download_preview_audio",
                    return_value=("https://example.test/preview.mp3", AudioSegment.silent(duration=30000), None),
                ),
                patch(
                    "musicround.services.automation._round_audio_components",
                    return_value=(
                        {"custom_audio_ms": {"intro": 1000, "replay": 1000, "outro": 1000}, "number_audio_ms": [1000]},
                        [],
                    ),
                ),
                patch(
                    "musicround.services.automation.inspect_pdf_quality",
                    return_value={"warnings": [], "ok": True},
                ),
                patch(
                    "musicround.services.automation.inspect_mp3_quality",
                    return_value={"warnings": [], "ok": True, "duration_seconds": 65},
                ),
            ):
                result = automation.inspect_round_package(
                    round_id, user_id=user.id, expected_song_count=1
                )

            assert result["ok"] is False
            assert result["status"] == "storage_unhealthy"
            assert result["storage"]["ok"] is False
            assert result["service_health"]["artifact_storage"]["ok"] is False
            assert result["service_health"]["spotify"]["status"] in {"ok", "warning", "error"}
            assert any(issue["code"] == "artifact_storage_missing" for issue in result["issues"])

    def test_inspect_round_package_requires_resolved_songs(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="Real", artist="Artist", deezer_id="123")
            round_id = automation.create_round(
                name="Unresolved Song",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]
            round_obj = db.session.get(Round, round_id)
            round_obj.songs = f"{song.id},999999"
            db.session.commit()

            with (
                patch(
                    "musicround.services.automation._download_preview_audio",
                    return_value=("https://example.test/preview.mp3", AudioSegment.silent(duration=30000), None),
                ),
                patch(
                    "musicround.services.automation._round_audio_components",
                    return_value=(
                        {"custom_audio_ms": {"intro": 1000, "replay": 1000, "outro": 1000}, "number_audio_ms": [1000]},
                        [],
                    ),
                ),
                patch(
                    "musicround.services.automation.inspect_pdf_quality",
                    return_value={"warnings": [], "ok": True},
                ),
                patch(
                    "musicround.services.automation.inspect_mp3_quality",
                    return_value={"warnings": [], "ok": True, "duration_seconds": 65},
                ),
            ):
                result = automation.inspect_round_package(
                    round_id, user_id=user.id, expected_song_count=2
                )

            assert result["ok"] is False
            assert result["status"] == "needs_more_songs"
            assert result["actual_song_count"] == 2
            assert result["resolved_song_count"] == 1
            assert any(
                issue["code"] == "resolved_song_count_mismatch"
                for issue in result["issues"]
            )
            assert result["song_slots"][0]["position"] == 1
            assert result["song_slots"][0]["resolved"] is True
            assert result["song_slots"][1] == {
                "position": 2,
                "stored_song_id": 999999,
                "resolved": False,
                "song": None,
            }
            assert result["remediation"][0]["positions"] == [2]

    def test_inspect_round_package_keeps_preview_failures_on_stored_positions(self, app):
        with app.app_context():
            user = _create_user()
            first_song = _create_song(title="First", artist="Artist", deezer_id="101")
            third_song = _create_song(title="Third", artist="Artist", deezer_id="303")
            round_id = automation.create_round(
                name="Gap Then Preview Failure",
                round_type="manual",
                song_ids=[first_song.id, third_song.id],
            )["round"]["id"]
            round_obj = db.session.get(Round, round_id)
            round_obj.songs = f"{first_song.id},999999,{third_song.id}"
            db.session.commit()

            def fake_download(song, _temp_dir):
                duration = 10000 if song.id == third_song.id else 30000
                return (
                    f"https://example.test/{song.id}.mp3",
                    AudioSegment.silent(duration=duration),
                    None,
                )

            with (
                patch(
                    "musicround.services.automation._download_preview_audio",
                    side_effect=fake_download,
                ),
                patch(
                    "musicround.services.automation._round_audio_components",
                    return_value=(
                        {"custom_audio_ms": {"intro": 1000, "replay": 1000, "outro": 1000}, "number_audio_ms": [1000, 1000]},
                        [],
                    ),
                ),
                patch(
                    "musicround.services.automation.inspect_pdf_quality",
                    return_value={"warnings": [], "ok": True},
                ),
                patch(
                    "musicround.services.automation.inspect_mp3_quality",
                    return_value={"warnings": [], "ok": True, "duration_seconds": 85},
                ),
            ):
                result = automation.inspect_round_package(
                    round_id,
                    user_id=user.id,
                    expected_song_count=3,
                    min_preview_seconds=20,
                )

            failed_checks = [
                check for check in result["preview_checks"] if check["issue_code"] == "preview_too_short"
            ]
            replace_actions = [
                action for action in result["remediation"] if action["action"] == "replace_position"
            ]
            assert failed_checks[0]["position"] == 3
            assert failed_checks[0]["stored_song_id"] == third_song.id
            assert replace_actions[0]["position"] == 3
            assert result["report"]["failed_positions"][0]["position"] == 3

    def test_round_repair_report_summarizes_multiple_failed_positions(self, app):
        with app.app_context():
            quality = {
                "round_id": 23,
                "round_name": "2026-07-23",
                "status": "needs_substitution",
                "ok": False,
                "expected_song_count": 8,
                "resolved_song_count": 8,
                "song_count": 8,
                "issues": [
                    {
                        "code": "missing_preview_url",
                        "message": "Position 4 has no preview.",
                        "song": {
                            "artist": "Kate Bush",
                            "title": "Running Up That Hill",
                        },
                    },
                    {
                        "code": "preview_too_short",
                        "message": "Position 7 preview is 10.0s.",
                        "song": {
                            "artist": "Example Artist",
                            "title": "Short Clip",
                        },
                    },
                ],
                "preview_checks": [
                    {
                        "ok": False,
                        "position": 4,
                        "song_id": 104,
                        "artist": "Kate Bush",
                        "title": "Running Up That Hill",
                        "issue_code": "missing_preview_url",
                    },
                    {
                        "ok": False,
                        "position": 7,
                        "song_id": 107,
                        "artist": "Example Artist",
                        "title": "Short Clip",
                        "issue_code": "preview_too_short",
                    },
                ],
                "remediation": [
                    {
                        "action": "replace_position",
                        "position": 4,
                        "artist": "Kate Bush",
                        "title": "Running Up That Hill",
                    },
                    {
                        "action": "replace_position",
                        "position": 7,
                        "artist": "Example Artist",
                        "title": "Short Clip",
                    },
                ],
            }

            report = automation._round_repair_report(quality)

            assert report["headline"].startswith("2026-07-23 is blocked:")
            assert report["status"] == "needs_substitution"
            assert sorted(item["position"] for item in report["failed_positions"]) == [4, 7]
            assert "Kate Bush - Running Up That Hill" in report["markdown"]
            assert "Example Artist - Short Clip" in report["markdown"]
            assert "Replace position 4" in report["markdown"]
            assert "Replace position 7" in report["markdown"]
            assert "suggest_replacement_songs" in report["next_step"]

    def test_inspect_round_package_warns_for_missing_preview(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="No Preview", artist="Artist", deezer_id="123")
            created = automation.create_round(
                name="Missing Preview",
                round_type="manual",
                song_ids=[song.id],
            )
            round_id = created["round"]["id"]
            app.config["deezer"] = type(
                "DeezerStub",
                (),
                {"get_track": lambda self, track_id: {"preview": None}},
            )()

            with (
                patch(
                    "musicround.services.automation._round_audio_components",
                    return_value=(
                        {"custom_audio_ms": {"intro": 1000, "replay": 1000, "outro": 1000}, "number_audio_ms": [1000]},
                        [],
                    ),
                ),
                patch(
                    "musicround.services.automation.inspect_pdf_quality",
                    return_value={"warnings": [], "ok": True},
                ),
                patch(
                    "musicround.services.automation.inspect_mp3_quality",
                    return_value={"warnings": [], "ok": True, "duration_seconds": 5},
                ),
            ):
                result = automation.inspect_round_package(
                    round_id, user_id=user.id, expected_song_count=1
                )

            assert result["ok"] is False
            assert result["status"] == "needs_substitution"
            assert any(issue["code"] == "missing_preview_url" for issue in result["issues"])
            assert result["preview_checks"][0]["issue_code"] == "missing_preview_url"
            assert result["remediation"][0]["action"] == "replace_position"
            assert result["report"]["status"] == "needs_substitution"
            assert result["report"]["failed_positions"][0]["position"] == 1
            assert "suggest_replacement_songs" in result["report"]["next_step"]
            assert "Replace position 1" in result["report"]["markdown"]

    def test_preview_lookup_failure_hides_exception_details(self, app, tmp_path):
        with app.app_context():
            song = _create_song(title="Lookup Fail", artist="Artist", deezer_id="123")
            app.config["deezer"] = type(
                "FailingDeezer",
                (),
                {
                    "get_track": lambda self, track_id: (
                        (_ for _ in ()).throw(RuntimeError("deezer token=secret traceback"))
                    )
                },
            )()

            preview_url, audio, issue = automation._download_preview_audio(song, str(tmp_path))

            assert preview_url is None
            assert audio is None
            assert issue["code"] == "deezer_lookup_failed"
            assert "Check the server logs" in issue["message"]
            assert "secret" not in issue["message"]
            assert "traceback" not in issue["message"]

    def test_preview_download_failure_hides_exception_details(self, app, tmp_path):
        with app.app_context():
            song = _create_song(title="Download Fail", artist="Artist", deezer_id="123")
            app.config["deezer"] = type(
                "PreviewDeezer",
                (),
                {
                    "get_track": lambda self, track_id: {
                        "preview": "https://example.test/preview.mp3?access_token=secret"
                    }
                },
            )()

            with patch(
                "musicround.services.automation.requests.get",
                side_effect=RuntimeError("http token=transport-secret traceback"),
            ):
                preview_url, audio, issue = automation._download_preview_audio(song, str(tmp_path))

            assert preview_url == "https://example.test/preview.mp3?access_token=secret"
            assert audio is None
            assert issue["code"] == "preview_download_failed"
            assert issue["details"] == {"preview_url_present": True}
            body = str(issue)
            assert "transport-secret" not in body
            assert "access_token" not in body
            assert "traceback" not in body

    def test_inspect_round_package_warns_for_short_preview(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="Short", artist="Artist", deezer_id="123")
            round_id = automation.create_round(
                name="Short Preview",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]

            with (
                patch(
                    "musicround.services.automation._download_preview_audio",
                    return_value=("https://example.test/short.mp3", AudioSegment.silent(duration=10000), None),
                ),
                patch(
                    "musicround.services.automation._round_audio_components",
                    return_value=(
                        {"custom_audio_ms": {"intro": 1000, "replay": 1000, "outro": 1000}, "number_audio_ms": [1000]},
                        [],
                    ),
                ),
                patch(
                    "musicround.services.automation.inspect_pdf_quality",
                    return_value={"warnings": [], "ok": True},
                ),
                patch(
                    "musicround.services.automation.inspect_mp3_quality",
                    return_value={"warnings": [], "ok": True, "duration_seconds": 25},
                ),
            ):
                result = automation.inspect_round_package(
                    round_id, user_id=user.id, expected_song_count=1
                )

            assert result["ok"] is False
            assert result["status"] == "needs_substitution"
            assert any(issue["code"] == "preview_too_short" for issue in result["issues"])

    def test_inspect_round_package_rejects_invalid_duration_parameters(self, app):
        with app.app_context():
            song = _create_song(title="Parameter", artist="Artist", deezer_id="123")
            round_id = automation.create_round(
                name="Bad Parameters",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]

            with pytest.raises(automation.AutomationError, match="must not exceed"):
                automation.inspect_round_package(
                    round_id,
                    expected_song_count=1,
                    min_preview_seconds=35,
                    max_preview_seconds=20,
                )

            with pytest.raises(automation.AutomationError, match="must not be negative"):
                automation.inspect_round_package(
                    round_id,
                    expected_song_count=1,
                    duration_tolerance_seconds=-1,
                )

            for parameter_name in ("min_preview_seconds", "max_preview_seconds", "duration_tolerance_seconds"):
                with pytest.raises(automation.AutomationError, match="must be finite"):
                    automation.inspect_round_package(
                        round_id,
                        expected_song_count=1,
                        **{parameter_name: float("nan")},
                    )
                with pytest.raises(automation.AutomationError, match="must be finite"):
                    automation.inspect_round_package(
                        round_id,
                        expected_song_count=1,
                        **{parameter_name: float("inf")},
                    )

    def test_inspect_round_package_tolerates_minor_mp3_duration_variance(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="Long Enough", artist="Artist", deezer_id="123")
            round_id = automation.create_round(
                name="Minor Variance",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]

            with (
                patch(
                    "musicround.services.automation._download_preview_audio",
                    return_value=("https://example.test/preview.mp3", AudioSegment.silent(duration=30000), None),
                ),
                patch(
                    "musicround.services.automation._round_audio_components",
                    return_value=(
                        {"custom_audio_ms": {"intro": 1000, "replay": 1000, "outro": 1000}, "number_audio_ms": [1000]},
                        [],
                    ),
                ),
                patch(
                    "musicround.services.automation.inspect_pdf_quality",
                    return_value={"warnings": [], "ok": True},
                ),
                patch(
                    "musicround.services.automation.inspect_mp3_quality",
                    return_value={"warnings": [], "ok": True, "duration_seconds": 50},
                ),
            ):
                result = automation.inspect_round_package(
                    round_id, user_id=user.id, expected_song_count=1
                )

            assert result["expected_duration_seconds"] == 65
            assert result["status"] == "ok"
            assert not any(
                issue["code"] == "round_mp3_duration_mismatch"
                for issue in result["issues"]
            )

    def test_inspect_round_package_warns_for_small_mp3_duration_shortfall(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="Warn Only", artist="Artist", deezer_id="123")
            round_id = automation.create_round(
                name="Small Shortfall",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]

            with (
                patch(
                    "musicround.services.automation._download_preview_audio",
                    return_value=("https://example.test/preview.mp3", AudioSegment.silent(duration=30000), None),
                ),
                patch(
                    "musicround.services.automation._round_audio_components",
                    return_value=(
                        {"custom_audio_ms": {"intro": 1000, "replay": 1000, "outro": 1000}, "number_audio_ms": [1000]},
                        [],
                    ),
                ),
                patch(
                    "musicround.services.automation.inspect_pdf_quality",
                    return_value={"warnings": [], "ok": True},
                ),
                patch(
                    "musicround.services.automation.inspect_mp3_quality",
                    return_value={"warnings": [], "ok": True, "duration_seconds": 50},
                ),
            ):
                result = automation.inspect_round_package(
                    round_id,
                    user_id=user.id,
                    expected_song_count=1,
                    duration_tolerance_seconds=10,
                )

            warning = next(
                issue for issue in result["issues"]
                if issue["code"] == "round_mp3_duration_mismatch"
            )
            assert result["expected_duration_seconds"] == 65
            assert result["status"] == "ok"
            assert result["ok"] is True
            assert warning["severity"] == "warning"
            assert result["blocking_issue_count"] == 0
            assert result["warnings"] == [warning]
            assert "Warnings" in result["report"]["markdown"]
            assert result["report"]["blockers"] == []

    def test_inspect_round_package_allows_realistic_full_round_render_variance(self, app):
        """A sub-30s render drift should not block an eight-song package."""
        with app.app_context():
            user = _create_user()
            songs = [
                _create_song(title=f"Song {index}", artist="Artist", deezer_id=str(index))
                for index in range(1, 9)
            ]
            round_id = automation.create_round(
                name="Realistic Render Drift",
                round_type="manual",
                song_ids=[song.id for song in songs],
            )["round"]["id"]

            with (
                patch(
                    "musicround.services.automation._download_preview_audio",
                    return_value=(
                        "https://example.test/preview.mp3",
                        AudioSegment.silent(duration=30000),
                        None,
                    ),
                ),
                patch(
                    "musicround.services.automation._round_audio_components",
                    return_value=(
                        {
                            "custom_audio_ms": {
                                "intro": 11000,
                                "replay": 11000,
                                "outro": 9800,
                            },
                            "number_audio_ms": [500] * 8,
                            "hint_audio_ms": {},
                        },
                        [],
                    ),
                ),
                patch(
                    "musicround.services.automation.inspect_pdf_quality",
                    return_value={"warnings": [], "ok": True},
                ),
                patch(
                    "musicround.services.automation.inspect_mp3_quality",
                    return_value={
                        "warnings": [],
                        "ok": True,
                        "duration_seconds": 504.8,
                    },
                ),
            ):
                result = automation.inspect_round_package(round_id, user_id=user.id)

            assert result["expected_duration_seconds"] == 519.8
            assert result["status"] == "ok"
            assert result["ok"] is True
            assert result["blocking_issue_count"] == 0
            assert not any(
                issue["code"] == "round_mp3_duration_mismatch"
                for issue in result["issues"]
            )

    def test_inspect_round_package_blocks_material_mp3_duration_shortfall(self, app):
        with app.app_context():
            user = _create_user()
            songs = [
                _create_song(title=f"Song {index}", artist="Artist", deezer_id=str(index))
                for index in range(1, 9)
            ]
            round_id = automation.create_round(
                name="Missing Replay Duration",
                round_type="manual",
                song_ids=[song.id for song in songs],
            )["round"]["id"]

            with (
                patch(
                    "musicround.services.automation._download_preview_audio",
                    return_value=(
                        "https://example.test/preview.mp3",
                        AudioSegment.silent(duration=20000),
                        None,
                    ),
                ),
                patch(
                    "musicround.services.automation._round_audio_components",
                    return_value=(
                        {
                            "custom_audio_ms": {
                                "intro": 1000,
                                "replay": 1000,
                                "outro": 1000,
                            },
                            "number_audio_ms": [1000] * 8,
                        },
                        [],
                    ),
                ),
                patch(
                    "musicround.services.automation.inspect_pdf_quality",
                    return_value={"warnings": [], "ok": True},
                ),
                patch(
                    "musicround.services.automation.inspect_mp3_quality",
                    return_value={
                        "warnings": [],
                        "ok": True,
                        "duration_seconds": 299,
                    },
                ),
            ):
                result = automation.inspect_round_package(round_id, user_id=user.id)

            assert result["expected_duration_seconds"] == 339
            assert result["status"] == "render_failed"
            mismatch = next(
                issue for issue in result["issues"]
                if issue["code"] == "round_mp3_duration_mismatch"
            )
            assert mismatch["severity"] == "error"

    def test_inspect_round_package_warns_for_large_mp3_duration_mismatch(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="Long Enough", artist="Artist", deezer_id="123")
            round_id = automation.create_round(
                name="Mismatch",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]

            with (
                patch(
                    "musicround.services.automation._download_preview_audio",
                    return_value=("https://example.test/preview.mp3", AudioSegment.silent(duration=30000), None),
                ),
                patch(
                    "musicround.services.automation._round_audio_components",
                    return_value=(
                        {"custom_audio_ms": {"intro": 1000, "replay": 1000, "outro": 1000}, "number_audio_ms": [1000]},
                        [],
                    ),
                ),
                patch(
                    "musicround.services.automation.inspect_pdf_quality",
                    return_value={"warnings": [], "ok": True},
                ),
                patch(
                    "musicround.services.automation.inspect_mp3_quality",
                    return_value={"warnings": [], "ok": True, "duration_seconds": 5},
                ),
            ):
                result = automation.inspect_round_package(
                    round_id, user_id=user.id, expected_song_count=1
                )

            assert result["expected_duration_seconds"] == 65
            assert result["status"] == "render_failed"
            mismatch = next(
                issue for issue in result["issues"]
                if issue["code"] == "round_mp3_duration_mismatch"
            )
            assert mismatch["severity"] == "error"

    def test_inspect_round_package_batch_splits_sendable_and_repair_rounds(self, app):
        with app.app_context():
            user = _create_user()

            def fake_inspect(round_id, **kwargs):
                if round_id == 1:
                    return {
                        "round_id": 1,
                        "round_name": "Ready",
                        "ok": True,
                        "status": "ok",
                        "expected_song_count": 8,
                        "actual_song_count": 8,
                        "resolved_song_count": 8,
                        "blocking_issue_count": 0,
                        "warnings": [],
                        "report": {
                            "headline": "Ready is ready to send.",
                            "summary": "8 songs, all checks passed.",
                            "failed_positions": [],
                            "actions": [],
                            "next_step": "Send the round email.",
                        },
                    }
                if round_id == 2:
                    return {
                        "round_id": 2,
                        "round_name": "Needs Repair",
                        "ok": False,
                        "status": "needs_substitution",
                        "expected_song_count": 8,
                        "actual_song_count": 8,
                        "resolved_song_count": 7,
                        "blocking_issue_count": 1,
                        "warnings": [],
                        "report": {
                            "headline": "Needs Repair is blocked.",
                            "summary": "1 blocker found.",
                            "failed_positions": [{"position": 4}],
                            "actions": [{"action": "replace_position", "message": "Replace position 4."}],
                            "next_step": "Replace position 4.",
                        },
                    }
                raise automation.AutomationError("Round 999 was not found.")

            with patch("musicround.services.automation.inspect_round_package", side_effect=fake_inspect):
                result = automation.inspect_round_package_batch([1, 2, 999], user_id=user.id)

            assert result["ok"] is False
            assert result["status"] == "error"
            assert result["count"] == 3
            assert result["ok_count"] == 1
            assert result["blocked_count"] == 1
            assert result["error_count"] == 1
            assert result["sendable_round_ids"] == [1]
            assert result["repair_round_ids"] == [2, 999]
            assert result["rounds"][1]["failed_positions"] == [{"position": 4}]
            assert result["rounds"][2]["status"] == "error"

    def test_inspect_round_package_batch_validates_ids(self, app):
        with app.app_context():
            with pytest.raises(automation.AutomationError, match="at least one"):
                automation.inspect_round_package_batch([])
            with pytest.raises(automation.AutomationError, match="positive"):
                automation.inspect_round_package_batch([0])
            with pytest.raises(automation.AutomationError, match="at most 50"):
                automation.inspect_round_package_batch(range(1, 52))

    def test_round_repair_plan_suggests_replacements_and_missing_songs(self, app):
        with app.app_context():
            repair_payload = {
                "quality": {
                    "round_id": 42,
                    "round_name": "Broken Round",
                    "ok": False,
                    "status": "needs_more_songs",
                    "actual_song_count": 7,
                    "resolved_song_count": 7,
                },
                "report": {
                    "failed_positions": [
                        {
                            "position": 2,
                            "song_id": 12,
                            "artist": "Broken Artist",
                            "title": "Broken Song",
                            "issue_code": "missing_preview_url",
                        }
                    ],
                    "actions": [
                        {
                            "action": "add_missing_track",
                            "message": "Add 1 missing song.",
                            "details": {
                                "action": "add_missing_track",
                                "expected_song_count": 8,
                                "actual_song_count": 7,
                            },
                        }
                    ],
                },
            }
            replacement = {
                "count": 1,
                "suggestions": [{"id": 99, "title": "Replacement", "artist": "Candidate"}],
            }
            additional = {
                "count": 1,
                "suggestions": [{"id": 100, "title": "Additional", "artist": "Candidate"}],
            }

            with (
                patch("musicround.services.automation.round_repair_report", return_value=repair_payload) as mock_report,
                patch("musicround.services.automation.suggest_replacement_songs", return_value=replacement) as mock_replace,
                patch("musicround.services.automation.suggest_additional_songs", return_value=additional) as mock_add,
            ):
                result = automation.round_repair_plan(
                    round_id=42,
                    user_id=7,
                    replacement_limit=3,
                    additional_limit=4,
                    verify_previews=True,
                    min_preview_seconds=21.5,
                )

            assert result["ok"] is False
            assert result["status"] == "needs_more_songs"
            assert result["missing_song_count"] == 1
            assert result["replacement_positions"][0]["position"] == 2
            assert result["replacement_positions"][0]["suggestions"] == replacement["suggestions"]
            assert result["additional_songs"] == additional
            assert result["next_actions"] == [
                "replace_failed_positions",
                "add_missing_songs",
                "regenerate_assets",
                "inspect_round_package",
            ]
            mock_report.assert_called_once()
            mock_replace.assert_called_once_with(
                round_id=42,
                position=2,
                limit=3,
                verify_previews=True,
                min_preview_seconds=21.5,
            )
            mock_add.assert_called_once_with(
                round_id=42,
                limit=4,
                verify_previews=True,
                min_preview_seconds=21.5,
            )

    def test_round_repair_plan_uses_unresolved_action_positions_without_adding_songs(self, app):
        with app.app_context():
            repair_payload = {
                "quality": {
                    "round_id": 43,
                    "round_name": "Unresolved Round",
                    "ok": False,
                    "status": "needs_more_songs",
                    "actual_song_count": 8,
                    "resolved_song_count": 7,
                },
                "report": {
                    "failed_positions": [],
                    "actions": [
                        {
                            "action": "replace_unresolved_positions",
                            "message": "Replace unresolved position 4.",
                            "details": {
                                "action": "replace_unresolved_positions",
                                "positions": [4],
                            },
                        }
                    ],
                },
            }

            with (
                patch("musicround.services.automation.round_repair_report", return_value=repair_payload),
                patch(
                    "musicround.services.automation.suggest_replacement_songs",
                    return_value={"count": 0, "suggestions": []},
                ) as mock_replace,
                patch("musicround.services.automation.suggest_additional_songs") as mock_add,
            ):
                result = automation.round_repair_plan(round_id=43)

            assert result["missing_song_count"] == 0
            assert result["additional_songs"] is None
            assert result["replacement_positions"] == [
                {
                    "position": 4,
                    "failed_song": {
                        "position": 4,
                        "issue_code": "unresolved_song",
                        "message": "Position 4: unresolved stored song ID.",
                    },
                    "count": 0,
                    "suggestions": [],
                }
            ]
            mock_replace.assert_called_once()
            mock_add.assert_not_called()

    def test_round_repair_plan_validates_limits(self, app):
        with app.app_context():
            with pytest.raises(automation.AutomationError, match="replacement_limit"):
                automation.round_repair_plan(round_id=1, replacement_limit=0)
            with pytest.raises(automation.AutomationError, match="additional_limit"):
                automation.round_repair_plan(round_id=1, additional_limit=51)

    def test_round_repair_plan_batch_continues_after_round_errors(self, app):
        with app.app_context():
            def fake_plan(round_id, **kwargs):
                if round_id == 1:
                    return {
                        "round_id": 1,
                        "round_name": "Ready Round",
                        "ok": True,
                        "status": "ok",
                        "next_actions": ["send_round_email"],
                    }
                if round_id == 2:
                    return {
                        "round_id": 2,
                        "round_name": "Needs Repair",
                        "ok": False,
                        "status": "needs_substitution",
                        "replacement_positions": [{"position": 3}],
                        "next_actions": [
                            "replace_failed_positions",
                            "regenerate_assets",
                            "inspect_round_package",
                        ],
                    }
                raise automation.AutomationError("Round 999 was not found.")

            with patch("musicround.services.automation.round_repair_plan", side_effect=fake_plan) as mock_plan:
                result = automation.round_repair_plan_batch(
                    [1, 2, 2, 999],
                    user_id=7,
                    replacement_limit=4,
                    additional_limit=6,
                    verify_previews=True,
                )

            assert result["ok"] is False
            assert result["status"] == "error"
            assert result["round_ids"] == [1, 2, 999]
            assert result["ready_count"] == 1
            assert result["repair_count"] == 1
            assert result["error_count"] == 1
            assert result["ready_round_ids"] == [1]
            assert result["repair_round_ids"] == [2, 999]
            assert result["plans"][0]["needs_repair"] is False
            assert result["plans"][1]["needs_repair"] is True
            assert result["plans"][2]["status"] == "error"
            assert mock_plan.call_count == 3
            assert mock_plan.call_args_list[0].kwargs["replacement_limit"] == 4
            assert mock_plan.call_args_list[0].kwargs["additional_limit"] == 6
            assert mock_plan.call_args_list[0].kwargs["verify_previews"] is True

    def test_round_repair_plan_batch_validates_ids(self, app):
        with app.app_context():
            with pytest.raises(automation.AutomationError, match="at least one"):
                automation.round_repair_plan_batch([])
            with pytest.raises(automation.AutomationError, match="positive"):
                automation.round_repair_plan_batch([-1])
            with pytest.raises(automation.AutomationError, match="at most 50"):
                automation.round_repair_plan_batch(range(1, 52))

    def test_round_audio_component_failures_hide_exception_details(self, app):
        with app.app_context():
            user = _create_user()

            with patch(
                "musicround.services.automation.AudioSegment.from_mp3",
                side_effect=RuntimeError("audio path=/srv/private token=secret"),
            ):
                components, issues = automation._round_audio_components(user, 1)

            assert components["custom_audio_ms"] == {}
            assert components["number_audio_ms"] == []
            assert {issue["code"] for issue in issues} == {
                "custom_audio_failed",
                "number_audio_failed",
            }
            body = str(issues)
            assert "secret" not in body
            assert "/srv/private" not in body
            assert "Check the server logs" in body

    def test_generate_round_mp3_missing_file_hides_internal_path(self, app, tmp_path):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="No Output", artist="Artist", deezer_id="123")
            round_id = automation.create_round(
                name="No Output Round",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]
            private_dir = tmp_path / "private-token-secret-rounds"
            private_dir.mkdir()
            app.config["ROUND_MP3_DIR"] = str(private_dir)
            expected_path = str(private_dir / f"round_{round_id}.mp3")
            real_exists = os.path.exists

            def fake_exists(path):
                if path == expected_path:
                    return False
                return real_exists(path)

            with (
                patch("musicround.routes.rounds.round_mp3", return_value={"success": True}),
                patch("musicround.services.automation.os.path.exists", side_effect=fake_exists),
            ):
                with pytest.raises(automation.AutomationError) as exc_info:
                    automation.generate_round_mp3(round_id, user_id=user.id)

            message = str(exc_info.value)
            assert message == automation.AUTOMATION_MP3_GENERATION_ERROR
            assert "private-token-secret" not in message

    def test_email_round_blocks_when_package_quality_fails(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="Bad", artist="Artist")
            round_id = automation.create_round(
                name="Blocked",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]
            _approve_round(round_id, reviewer=user)

            with (
                patch(
                    "musicround.services.automation.generate_round_assets",
                    return_value={"pdf": {"path": "/tmp/no.pdf"}, "mp3": {"path": "/tmp/no.mp3"}},
                ),
                patch(
                    "musicround.services.automation.inspect_round_package",
                    return_value={
                        "ok": False,
                        "status": "needs_substitution",
                        "hints": ["missing preview"],
                    },
                ),
                patch(
                    "musicround.services.automation.send_round_blocked_notification",
                    return_value={"sent": True, "skipped": False, "reason": None},
                ) as mock_notify,
                patch("musicround.services.automation.send_email") as mock_send,
            ):
                with pytest.raises(automation.AutomationError, match="quality gate") as exc_info:
                    automation.email_round(round_id, user_id=user.id)

            assert not mock_send.called
            mock_notify.assert_called_once()
            assert mock_notify.call_args.kwargs["round_id"] == round_id
            assert exc_info.value.details["status"] == "needs_substitution"
            assert exc_info.value.details["report"]["status"] == "needs_substitution"
            export = RoundExport.query.filter_by(round_id=round_id).one()
            assert export.status == "failed"
            round_obj = db.session.get(Round, round_id)
            assert round_obj.review_status == "blocked"

    def test_email_round_blocks_draft_until_approved(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="Draft", artist="Artist")
            round_id = automation.create_round(
                name="Draft Round",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]

            with patch("musicround.services.automation.generate_round_assets") as mock_assets:
                with pytest.raises(automation.AutomationError, match="approve") as exc_info:
                    automation.email_round(round_id, user_id=user.id)

            mock_assets.assert_not_called()
            assert exc_info.value.details["status"] == "review_not_approved"
            assert exc_info.value.details["review_status"] == "draft"
            assert RoundExport.query.filter_by(round_id=round_id).count() == 0

    def test_email_round_admin_override_can_send_draft_and_marks_sent(self, app, tmp_path):
        with app.app_context():
            user = _create_user()
            admin = _create_user(username="admin", email="admin@example.test")
            admin.is_admin = True
            song = _create_song(title="Override", artist="Artist")
            round_id = automation.create_round(
                name="Override Round",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]
            pdf_path = tmp_path / "round.pdf"
            mp3_path = tmp_path / "round.mp3"
            pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
            mp3_path.write_bytes(b"mp3")

            with (
                patch(
                    "musicround.services.automation.generate_round_assets",
                    return_value={"pdf": {"path": str(pdf_path)}, "mp3": {"path": str(mp3_path)}},
                ),
                patch(
                    "musicround.services.automation.inspect_round_package",
                    return_value={"ok": True, "status": "ok"},
                ),
                patch(
                    "musicround.services.automation.send_email",
                    return_value=(True, "sent"),
                ),
            ):
                result = automation.email_round(
                    round_id,
                    user_id=user.id,
                    admin_override_user_id=admin.id,
                    review_override_reason="Smoke test",
                )

            assert result["success"] is True
            assert result["review_gate"]["override"] is True
            round_obj = db.session.get(Round, round_id)
            assert round_obj.review_status == "sent"
            export = RoundExport.query.filter_by(round_id=round_id).one()
            assert export.status == "success"

    def test_schedule_round_email_stores_pending_export(self, app):
        with app.app_context():
            _configure_mail(app)
            user = _create_user()
            song = _create_song(title="Scheduled", artist="Artist")
            round_id = automation.create_round(
                name="Thursday Round",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]
            _approve_round(round_id, reviewer=user)
            scheduled_for, _, scheduled_at = _future_schedule_pair()

            with (
                patch(
                    "musicround.services.automation.generate_round_assets",
                    return_value={"pdf": {"path": "/tmp/round.pdf"}, "mp3": {"path": "/tmp/round.mp3"}},
                ),
                patch(
                    "musicround.services.automation.inspect_round_package",
                    return_value={"ok": True, "status": "ok"},
                ),
            ):
                result = automation.schedule_round_email(
                    round_id,
                    scheduled_for=scheduled_for,
                    user_id=user.id,
                    subject="Scheduled subject",
                )

            export = RoundExport.query.get(result["export"]["id"])
            assert result["scheduled"] is True
            assert result["quality"]["status"] == "ok"
            assert export.status == "scheduled"
            assert export.destination == user.email
            assert export.subject == "Scheduled subject"
            assert result["export"]["scheduled_for"] == f"{scheduled_at.isoformat()}Z"

    def test_schedule_round_email_blocks_draft_before_generation(self, app):
        with app.app_context():
            _configure_mail(app)
            user = _create_user()
            song = _create_song(title="Draft Scheduled", artist="Artist")
            round_id = automation.create_round(
                name="Draft Scheduled Round",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]
            scheduled_for, _, _ = _future_schedule_pair()

            with patch("musicround.services.automation.generate_round_assets") as mock_assets:
                with pytest.raises(automation.AutomationError, match="approve") as exc_info:
                    automation.schedule_round_email(
                        round_id,
                        scheduled_for=scheduled_for,
                        user_id=user.id,
                    )

            mock_assets.assert_not_called()
            assert exc_info.value.details["status"] == "review_not_approved"
            assert RoundExport.query.filter_by(round_id=round_id).count() == 0

    def test_schedule_round_email_rejects_review_override(self, app):
        with app.app_context():
            _configure_mail(app)
            user = _create_user()
            admin = _create_user(username="schedule-admin", email="schedule-admin@example.test")
            admin.is_admin = True
            song = _create_song(title="Scheduled Override", artist="Artist")
            round_id = automation.create_round(
                name="Scheduled Override Round",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]
            _approve_round(round_id, reviewer=user)
            scheduled_for, _, _ = _future_schedule_pair()

            with patch("musicround.services.automation.generate_round_assets") as mock_assets:
                with pytest.raises(automation.AutomationError) as exc_info:
                    automation.schedule_round_email(
                        round_id,
                        scheduled_for=scheduled_for,
                        user_id=user.id,
                        admin_override_user_id=admin.id,
                        review_override_reason="Do this later.",
                    )

            mock_assets.assert_not_called()
            assert exc_info.value.details["status"] == "scheduled_review_override_forbidden"
            assert RoundExport.query.filter_by(round_id=round_id).count() == 0

    def test_round_review_payload_includes_review_inputs_and_repair_hints(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(
                title="Payload Song",
                artist="Payload Artist",
                preview_url="https://example.test/payload.mp3",
                used_count=2,
                last_used=datetime.utcnow(),
            )
            round_id = automation.create_round(
                name="Payload Round",
                round_type="manual",
                song_ids=[song.id],
                user_id=user.id,
            )["round"]["id"]
            script = RoundAudioScript(
                round_id=round_id,
                user_id=user.id,
                script_type="intro",
                text="Welcome to the payload round.",
                status="approved",
                selected=True,
            )
            db.session.add(script)
            db.session.commit()

            with patch(
                "musicround.services.automation.round_repair_report",
                return_value={"ok": False, "status": "needs_substitution", "hints": ["replace position 1"]},
            ):
                result = automation.round_review_payload(round_id, user_id=user.id)

            assert result["round"]["review_status"] == "draft"
            assert result["review_gate"]["requires_approval"] is True
            assert result["songs"][0]["position"] == 1
            assert result["songs"][0]["preview_status"]["has_preview"] is True
            assert result["songs"][0]["usage_warning"]["song"]["id"] == song.id
            assert result["audio_scripts"][0]["script_type"] == "intro"
            assert result["quality"]["status"] == "needs_substitution"
            assert result["repair_hints"] == ["replace position 1"]

    def test_update_round_review_status_is_lightweight_by_default(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="Lightweight Review", artist="Artist")
            round_id = automation.create_round(
                name="Lightweight Review Round",
                round_type="manual",
                song_ids=[song.id],
                user_id=user.id,
            )["round"]["id"]

            with patch("musicround.services.automation.round_repair_report") as mock_repair:
                result = automation.update_round_review_status(
                    round_id,
                    review_status="reviewed",
                    notes="Ready for final approval.",
                    reviewer_user_id=user.id,
                )

            mock_repair.assert_not_called()
            assert result["updated"] is True
            assert "review_payload" not in result
            assert result["round"]["review_status"] == "reviewed"

    def test_update_round_review_status_can_return_payload_when_requested(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="Payload Review", artist="Artist")
            round_id = automation.create_round(
                name="Payload Review Round",
                round_type="manual",
                song_ids=[song.id],
                user_id=user.id,
            )["round"]["id"]

            with patch(
                "musicround.services.automation.round_repair_report",
                return_value={"ok": True, "status": "ok", "hints": []},
            ) as mock_repair:
                result = automation.update_round_review_status(
                    round_id,
                    review_status="approved",
                    reviewer_user_id=user.id,
                    include_review_payload=True,
                )

            mock_repair.assert_called_once()
            assert result["review_payload"]["quality"]["status"] == "ok"

    def test_update_round_review_status_rejects_manual_sent(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="Manual Sent", artist="Artist")
            round_id = automation.create_round(
                name="Manual Sent Round",
                round_type="manual",
                song_ids=[song.id],
                user_id=user.id,
            )["round"]["id"]

            with pytest.raises(automation.AutomationError, match="review_status"):
                automation.update_round_review_status(
                    round_id,
                    review_status="sent",
                    reviewer_user_id=user.id,
                )

    def test_schedule_round_email_blocks_past_delivery_before_generation(self, app):
        with app.app_context():
            _configure_mail(app)
            user = _create_user()
            song = _create_song(title="Past Scheduled", artist="Artist")
            round_id = automation.create_round(
                name="Past Thursday Round",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]
            scheduled_for = (datetime.utcnow() - timedelta(minutes=5)).replace(microsecond=0)

            with patch("musicround.services.automation.generate_round_assets") as mock_assets:
                with pytest.raises(automation.AutomationError, match="future") as exc_info:
                    automation.schedule_round_email(
                        round_id,
                        scheduled_for=f"{scheduled_for.isoformat()}Z",
                        user_id=user.id,
                    )

            mock_assets.assert_not_called()
            assert exc_info.value.details["status"] == "schedule_in_past"
            assert RoundExport.query.filter_by(round_id=round_id).count() == 0

    def test_schedule_round_email_can_replace_existing_pending_export(self, app):
        with app.app_context():
            _configure_mail(app)
            user = _create_user()
            song = _create_song(title="Replace Scheduled", artist="Artist")
            round_id = automation.create_round(
                name="Replace Thursday Round",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]
            _approve_round(round_id, reviewer=user)
            existing = RoundExport(
                round_id=round_id,
                user_id=user.id,
                export_type="email",
                destination=user.email,
                include_mp3s=True,
                status="scheduled",
                scheduled_for=(datetime.utcnow() + timedelta(days=3)).replace(microsecond=0),
            )
            db.session.add(existing)
            db.session.commit()
            existing_id = existing.id
            scheduled_for, _, _ = _future_schedule_pair(days=14)

            with (
                patch(
                    "musicround.services.automation.generate_round_assets",
                    return_value={"pdf": {"path": "/tmp/round.pdf"}, "mp3": {"path": "/tmp/round.mp3"}},
                ),
                patch(
                    "musicround.services.automation.inspect_round_package",
                    return_value={"ok": True, "status": "ok"},
                ),
            ):
                result = automation.schedule_round_email(
                    round_id,
                    scheduled_for=scheduled_for,
                    user_id=user.id,
                    replace_existing=True,
                )

            old_export = RoundExport.query.get(existing_id)
            new_export = RoundExport.query.get(result["export"]["id"])
            assert old_export.status == "superseded"
            assert old_export.error_message == "Replaced by a newer scheduled delivery."
            assert new_export.status == "scheduled"
            assert result["replaced_exports"][0]["id"] == existing_id
            assert RoundExport.query.filter_by(
                round_id=round_id,
                user_id=user.id,
                export_type="email",
                status="scheduled",
            ).count() == 1

    def test_schedule_round_email_blocks_missing_email_config_before_generation(self, app):
        with app.app_context():
            app.config["MAIL_HOST"] = None
            user = _create_user()
            song = _create_song(title="No Mail", artist="Artist")
            round_id = automation.create_round(
                name="No Mail Config",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]
            scheduled_for, _, _ = _future_schedule_pair()

            with patch("musicround.services.automation.generate_round_assets") as mock_assets:
                with pytest.raises(automation.AutomationError, match="Email configuration") as exc_info:
                    automation.schedule_round_email(
                        round_id,
                        scheduled_for=scheduled_for,
                        user_id=user.id,
                    )

            mock_assets.assert_not_called()
            assert exc_info.value.details["status"] == "email_unhealthy"
            assert "email" in exc_info.value.details["service_health"]
            assert RoundExport.query.filter_by(round_id=round_id).count() == 0

    def test_schedule_round_email_blocks_when_quality_fails(self, app):
        with app.app_context():
            _configure_mail(app)
            user = _create_user()
            song = _create_song(title="Scheduled Bad", artist="Artist")
            round_id = automation.create_round(
                name="Bad Thursday Round",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]
            _approve_round(round_id, reviewer=user)
            scheduled_for, _, _ = _future_schedule_pair()

            with (
                patch(
                    "musicround.services.automation.generate_round_assets",
                    return_value={"pdf": {"path": "/tmp/round.pdf"}, "mp3": {"path": "/tmp/round.mp3"}},
                ),
                patch(
                    "musicround.services.automation.inspect_round_package",
                    return_value={
                        "ok": False,
                        "status": "needs_substitution",
                        "hints": ["missing preview"],
                        "report": {"status": "needs_substitution"},
                    },
                ),
            ):
                with pytest.raises(automation.AutomationError, match="quality gate") as exc_info:
                    automation.schedule_round_email(
                        round_id,
                        scheduled_for=scheduled_for,
                        user_id=user.id,
                    )

            assert exc_info.value.details["scheduled"] is False
            assert RoundExport.query.filter_by(round_id=round_id).count() == 0

    def test_schedule_round_email_blocks_when_storage_unhealthy_before_generation(self, app):
        with app.app_context():
            _configure_mail(app)
            user = _create_user()
            song = _create_song(title="Storage Bad", artist="Artist")
            round_id = automation.create_round(
                name="Unwritable Thursday Round",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]
            _approve_round(round_id, reviewer=user)
            app.config["ROUND_MP3_DIR"] = os.path.join(app.instance_path, "missing-rounds")
            scheduled_for, _, _ = _future_schedule_pair()

            with patch("musicround.services.automation.generate_round_pdf") as mock_pdf:
                with pytest.raises(automation.AutomationError, match="storage") as exc_info:
                    automation.schedule_round_email(
                        round_id,
                        scheduled_for=scheduled_for,
                        user_id=user.id,
                    )

            mock_pdf.assert_not_called()
            assert exc_info.value.details["ok"] is False
            assert RoundExport.query.filter_by(round_id=round_id).count() == 0

    def test_generate_assets_storage_error_hides_exception_text(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="Unsafe Storage", artist="Artist")
            round_id = automation.create_round(
                name="Unsafe Storage Round",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]

            with patch(
                "musicround.services.automation.require_round_artifact_storage",
                side_effect=RuntimeError("filesystem secret token=storage-secret traceback"),
            ):
                with pytest.raises(automation.AutomationError) as exc_info:
                    automation.generate_round_assets(round_id, user_id=user.id)

            message = str(exc_info.value)
            assert message == automation.AUTOMATION_STORAGE_ERROR
            assert exc_info.value.details
            assert "storage-secret" not in message
            assert "traceback" not in message

    def test_generate_assets_returns_round_review_url_path(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="Review Link", artist="Artist")
            round_id = automation.create_round(
                name="Review Link Round",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]

            with (
                patch(
                    "musicround.services.automation.generate_round_pdf",
                    return_value={"round_id": round_id, "path": "/tmp/round.pdf", "bytes": 12},
                ),
                patch(
                    "musicround.services.automation.generate_round_mp3",
                    return_value={"round_id": round_id, "path": "/tmp/round.mp3", "bytes": 34},
                ),
            ):
                result = automation.generate_round_assets(round_id, user_id=user.id)

            assert result["round_id"] == round_id
            assert result["review_url_path"] == f"/rounds/{round_id}/bundle-review"
            assert result["pdf"]["path"] == "/tmp/round.pdf"
            assert result["mp3"]["path"] == "/tmp/round.mp3"

    def test_generate_round_assets_batch_continues_after_round_errors(self, app):
        with app.app_context():
            def fake_generate(round_id, **kwargs):
                if round_id == 1:
                    return {
                        "round_id": 1,
                        "review_url_path": "/rounds/1/bundle-review",
                        "pdf": {"path": "/tmp/round1.pdf"},
                    }
                raise automation.AutomationError("Round 999 was not found.")

            with patch("musicround.services.automation.generate_round_assets", side_effect=fake_generate) as mock_generate:
                result = automation.generate_round_assets_batch(
                    [1, 1, 999],
                    user_id=7,
                    include_pdf=True,
                    include_mp3=False,
                )

            assert result["ok"] is False
            assert result["status"] == "error"
            assert result["round_ids"] == [1, 999]
            assert result["count"] == 2
            assert result["success_count"] == 1
            assert result["error_count"] == 1
            assert result["generated_round_ids"] == [1]
            assert result["failed_round_ids"] == [999]
            assert result["results"][0]["review_url_path"] == "/rounds/1/bundle-review"
            assert result["results"][1]["status"] == "error"
            assert mock_generate.call_count == 2
            assert mock_generate.call_args_list[0].kwargs == {
                "round_id": 1,
                "user_id": 7,
                "include_pdf": True,
                "include_mp3": False,
            }

    def test_generate_round_assets_batch_validates_ids(self, app):
        with app.app_context():
            with pytest.raises(automation.AutomationError, match="at least one"):
                automation.generate_round_assets_batch([])
            with pytest.raises(automation.AutomationError, match="positive"):
                automation.generate_round_assets_batch([0])
            with pytest.raises(automation.AutomationError, match="at most 50"):
                automation.generate_round_assets_batch(range(1, 52))

    def test_list_scheduled_round_emails_returns_pending_exports(self, app):
        with app.app_context():
            _configure_mail(app)
            user = _create_user()
            song = _create_song(title="Listed", artist="Artist")
            round_id = automation.create_round(
                name="Listed Round",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]
            _approve_round(round_id, reviewer=user)
            scheduled_for, _, _ = _future_schedule_pair()
            with (
                patch(
                    "musicround.services.automation.generate_round_assets",
                    return_value={"pdf": {"path": "/tmp/round.pdf"}, "mp3": {"path": "/tmp/round.mp3"}},
                ),
                patch(
                    "musicround.services.automation.inspect_round_package",
                    return_value={"ok": True, "status": "ok"},
                ),
            ):
                automation.schedule_round_email(
                    round_id,
                    scheduled_for=scheduled_for,
                    user_id=user.id,
                )

            result = automation.list_scheduled_round_emails(user_id=user.id)

            assert result["count"] == 1
            assert result["scheduled_exports"][0]["round_id"] == round_id
            assert result["scheduled_exports"][0]["status"] == "scheduled"

    def test_cancel_scheduled_round_email_marks_pending_export_cancelled(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="Cancel Listed", artist="Artist")
            round_id = automation.create_round(
                name="Cancel Listed Round",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]
            export = RoundExport(
                round_id=round_id,
                user_id=user.id,
                export_type="email",
                destination=user.email,
                include_mp3s=True,
                status="scheduled",
                scheduled_for=datetime(2026, 7, 9, 17, 0),
            )
            db.session.add(export)
            db.session.commit()
            export_id = export.id

            result = automation.cancel_scheduled_round_email(
                export_id=export_id,
                user_id=user.id,
                reason="No quiz this week.",
            )

            export = RoundExport.query.get(export_id)
            assert result["cancelled"] is True
            assert result["export"]["status"] == "cancelled"
            assert export.status == "cancelled"
            assert export.processed_at is not None
            assert export.error_message == "No quiz this week."

    def test_cancel_scheduled_round_email_blocks_processed_export(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="Already Sent", artist="Artist")
            round_id = automation.create_round(
                name="Already Sent Round",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]
            export = RoundExport(
                round_id=round_id,
                user_id=user.id,
                export_type="email",
                destination=user.email,
                include_mp3s=True,
                status="success",
                scheduled_for=datetime(2026, 7, 9, 17, 0),
            )
            db.session.add(export)
            db.session.commit()

            with pytest.raises(automation.AutomationError, match="already success"):
                automation.cancel_scheduled_round_email(export_id=export.id, user_id=user.id)

    def test_process_due_scheduled_round_emails_sends_due_exports(self, app):
        with app.app_context():
            _configure_mail(app)
            user = _create_user()
            song = _create_song(title="Due", artist="Artist")
            round_id = automation.create_round(
                name="Due Round",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]
            _approve_round(round_id, reviewer=user)
            scheduled_for, due_at, _ = _future_schedule_pair()
            with (
                patch(
                    "musicround.services.automation.generate_round_assets",
                    return_value={"pdf": {"path": "/tmp/round.pdf"}, "mp3": {"path": "/tmp/round.mp3"}},
                ),
                patch(
                    "musicround.services.automation.inspect_round_package",
                    return_value={"ok": True, "status": "ok"},
                ),
            ):
                scheduled = automation.schedule_round_email(
                    round_id,
                    scheduled_for=scheduled_for,
                    user_id=user.id,
                )

            with patch(
                "musicround.services.automation.email_round",
                return_value={"success": True, "message": "sent"},
            ) as mock_email:
                result = automation.process_due_scheduled_round_emails(
                    now=due_at,
                )

            assert result["processed_count"] == 1
            mock_email.assert_called_once()
            export = RoundExport.query.get(scheduled["export"]["id"])
            assert export.status == "success"
            assert export.processed_at is not None

    def test_process_due_scheduled_round_email_hides_exception_text(self, app):
        with app.app_context():
            _configure_mail(app)
            user = _create_user()
            song = _create_song(title="Due Failure", artist="Artist")
            round_id = automation.create_round(
                name="Due Failure Round",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]
            _approve_round(round_id, reviewer=user)
            scheduled_for, due_at, _ = _future_schedule_pair()
            with (
                patch(
                    "musicround.services.automation.generate_round_assets",
                    return_value={"pdf": {"path": "/tmp/round.pdf"}, "mp3": {"path": "/tmp/round.mp3"}},
                ),
                patch(
                    "musicround.services.automation.inspect_round_package",
                    return_value={"ok": True, "status": "ok"},
                ),
            ):
                scheduled = automation.schedule_round_email(
                    round_id,
                    scheduled_for=scheduled_for,
                    user_id=user.id,
                )

            with patch(
                "musicround.services.automation.email_round",
                side_effect=RuntimeError("smtp-secret token=mail-secret traceback"),
            ):
                result = automation.process_due_scheduled_round_emails(
                    now=due_at,
                )

            body = str(result)
            assert result["processed_count"] == 1
            assert result["results"][0]["error"] == automation.AUTOMATION_SCHEDULED_EMAIL_ERROR
            assert "smtp-secret" not in body
            assert "mail-secret" not in body
            assert "traceback" not in body
            export = RoundExport.query.get(scheduled["export"]["id"])
            assert export.status == "failed"
            assert export.error_message == automation.AUTOMATION_SCHEDULED_EMAIL_ERROR

    def test_process_due_scheduled_round_email_persists_quality_feedback(self, app):
        with app.app_context():
            _configure_mail(app)
            user = _create_user()
            song = _create_song(title="Due Quality Failure", artist="Artist")
            round_id = automation.create_round(
                name="Due Quality Failure Round",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]
            _approve_round(round_id, reviewer=user)
            scheduled_for, due_at, _ = _future_schedule_pair()
            with (
                patch(
                    "musicround.services.automation.generate_round_assets",
                    return_value={"pdf": {"path": "/tmp/round.pdf"}, "mp3": {"path": "/tmp/round.mp3"}},
                ),
                patch(
                    "musicround.services.automation.inspect_round_package",
                    return_value={"ok": True, "status": "ok"},
                ),
            ):
                scheduled = automation.schedule_round_email(
                    round_id,
                    scheduled_for=scheduled_for,
                    user_id=user.id,
                )

            quality_details = {
                "success": False,
                "status": "needs_substitution",
                "quality": {
                    "status": "needs_substitution",
                    "report": {
                        "headline": "Due Quality Failure Round is blocked: needs_substitution.",
                    },
                },
                "report": {
                    "headline": "Due Quality Failure Round is blocked: needs_substitution.",
                },
            }
            with patch(
                "musicround.services.automation.email_round",
                side_effect=automation.AutomationError(
                    "Round quality gate failed: preview missing token=secret",
                    details=quality_details,
                ),
            ):
                result = automation.process_due_scheduled_round_emails(
                    now=due_at,
                )

            body = str(result)
            assert result["processed_count"] == 1
            assert result["results"][0]["error"] == (
                "Due Quality Failure Round is blocked: needs_substitution."
            )
            assert "token=secret" not in body
            export = RoundExport.query.get(scheduled["export"]["id"])
            assert export.status == "failed"
            assert export.error_message == (
                "Due Quality Failure Round is blocked: needs_substitution."
            )


class TestTTSAutomation:
    """Tests for TTS snippet assignment."""

    def test_generate_tts_snippet_updates_user_audio_path(self, app):
        with app.app_context():
            user = _create_user()

            with patch("musicround.services.automation.generate_tts_mp3") as mock_tts:
                mock_tts.return_value = "custommp3/agentuser/intro.mp3"
                result = automation.generate_tts_snippet(
                    user_id=user.id,
                    mp3_type="intro",
                    text="Welcome to the quiz",
                    service="openai",
                )

            assert result["path"] == "custommp3/agentuser/intro.mp3"
            assert User.query.get(user.id).intro_mp3 == "custommp3/agentuser/intro.mp3"


class TestDatastoreCrudAutomation:
    """Tests for generic datastore CRUD operations exposed through MCP."""

    def test_datastore_schema_lists_mapped_models(self, app):
        with app.app_context():
            schema = automation.datastore_schema()

            assert "song" in schema["object_types"]
            assert "round" in schema["object_types"]
            assert "round_access_event" in schema["object_types"]
            assert "user" in schema["object_types"]
            song_schema = next(
                item for item in schema["objects"] if item["object_type"] == "song"
            )
            assert song_schema["primary_key"] == ["id"]
            assert any(column["name"] == "title" for column in song_schema["columns"])

    def test_crud_lifecycle_for_single_primary_key_object(self, app):
        with app.app_context():
            created = automation.create_datastore_object("tag", {"name": "warmup"})
            tag_id = created["object"]["id"]

            listed = automation.list_datastore_objects(
                "tag", filters={"name": "warmup"}, order_by="id"
            )
            fetched = automation.get_datastore_object("tag", tag_id)
            updated = automation.update_datastore_object(
                "tag", tag_id, {"name": "opener"}
            )
            deleted = automation.delete_datastore_object("tag", tag_id)

            assert created["object_type"] == "tag"
            assert listed["total"] == 1
            assert fetched["object"]["name"] == "warmup"
            assert updated["object"]["name"] == "opener"
            assert deleted["deleted"] is True
            assert Tag.query.get(tag_id) is None

    def test_crud_supports_composite_primary_keys(self, app):
        with app.app_context():
            song = _create_song(title="Composite", artist="Key")
            tag = Tag(name="linked")
            db.session.add(tag)
            db.session.commit()

            created = automation.create_datastore_object(
                "song_tag", {"song_id": song.id, "tag_id": tag.id}
            )
            fetched = automation.get_datastore_object(
                "song_tag", {"song_id": song.id, "tag_id": tag.id}
            )
            deleted = automation.delete_datastore_object(
                "song_tag", {"song_id": song.id, "tag_id": tag.id}
            )

            assert created["object"]["song_id"] == song.id
            assert fetched["object"]["tag_id"] == tag.id
            assert deleted["deleted"] is True
            assert SongTag.query.count() == 0

    def test_user_sensitive_fields_are_redacted_by_default(self, app):
        with app.app_context():
            user = _create_user()
            user.spotify_token = "secret-token"
            db.session.commit()

            result = automation.get_datastore_object("user", user.id)

            assert result["object"]["spotify_token"] == "[redacted]"
            assert result["object"]["password_hash"] == "[redacted]"


class TestAgentPlanningAutomation:
    """Tests for agent-facing planning and review helpers."""

    def test_import_progress_events_returns_queue_and_job_payload(self, app):
        with app.app_context():
            user = _create_user()
            queue = ImportQueue()
            app.config["IMPORT_QUEUE"] = queue
            record = ImportJobRecord(
                service_name="spotify",
                item_type="playlist",
                item_id="playlist123",
                priority=5,
                user_id=user.id,
                status="pending",
            )
            db.session.add(record)
            db.session.commit()
            queue.enqueue_record(record)

            result = automation.import_progress_events(user_id=user.id)

            assert result["queue_initialized"] is True
            assert result["queue_size"] == 1
            assert result["stats"]["pending"] == 1
            assert result["active_jobs"][0]["id"] == record.id
            assert result["queue_snapshot"][0]["record_id"] == record.id

    def test_import_progress_events_includes_repair_metadata(self, app):
        with app.app_context():
            user = _create_user(username="repairmeta", email="repairmeta@example.test")
            record = ImportJobRecord(
                service_name="spotify",
                item_type="playlist",
                item_id="playlist-needs-retry",
                priority=5,
                user_id=user.id,
                status="dead_letter",
                attempt_count=3,
                max_attempts=3,
                imported_count=2,
                error_message="manual review required",
            )
            db.session.add(record)
            db.session.commit()

            result = automation.import_progress_events(user_id=user.id)
            job = result["recent_jobs"][0]

            assert job["retryable"] is True
            assert job["terminal"] is True
            assert job["progress_percent"] == 100
            assert job["progress_label"] == "Manual review required"
            assert any("Reset attempts" in hint for hint in job["repair_hints"])
            assert job["failed_position_hints"] == []

    def test_import_progress_events_includes_failed_position_hints(self, app):
        with app.app_context():
            user = _create_user(username="positionmeta", email="positionmeta@example.test")
            record = ImportJobRecord(
                service_name="spotify",
                item_type="playlist",
                item_id="playlist-needs-position-repair",
                priority=5,
                user_id=user.id,
                status="completed",
                imported_count=1,
                skipped_count=1,
                result_metadata=json.dumps({
                    "playlist_positions": [
                        {
                            "position": 1,
                            "artist": "Resolved Artist",
                            "title": "Resolved Track",
                            "song_id": 123,
                            "status": "resolved",
                            "reason": None,
                        },
                        {
                            "position": 2,
                            "artist": "Broken Artist",
                            "title": "Broken Track",
                            "song_id": None,
                            "status": "failed",
                            "reason": "missing_spotify_track_id",
                        },
                    ],
                }),
            )
            db.session.add(record)
            db.session.commit()

            result = automation.import_progress_events(user_id=user.id)
            job = result["recent_jobs"][0]

            assert job["failed_position_hints"] == [
                {
                    "position": 2,
                    "artist": "Broken Artist",
                    "title": "Broken Track",
                    "song_id": None,
                    "status": "failed",
                    "reason": "missing_spotify_track_id",
                    "message": (
                        "Review playlist position 2: Broken Artist - Broken Track "
                        "(missing_spotify_track_id)."
                    ),
                }
            ]
            assert any("failed_position_hints" in hint for hint in job["repair_hints"])

    def test_parse_text_playlist_marks_rows_that_need_review(self, app):
        with app.app_context():
            result = automation.parse_text_playlist(
                "1. Shania Twain - Man! I Feel Like A Woman!\n"
                "Harry Styles - As It Was\n"
                "Mystery Song Without Artist\n"
            )

            assert result["count"] == 3
            assert result["candidates"][0]["artist"] == "Shania Twain"
            assert result["candidates"][0]["title"] == "Man! I Feel Like A Woman!"
            assert result["low_confidence_count"] == 1
            assert result["low_confidence"][0]["issues"] == ["missing_artist"]
            assert result["ready_for_import"] is False

    def test_parse_text_playlist_reads_headered_csv_columns(self, app):
        with app.app_context():
            result = automation.parse_text_playlist(
                "artist,title\n"
                "Harry Styles,As It Was\n"
                "Shania Twain,Man! I Feel Like A Woman!\n"
            )

            assert result["count"] == 2
            assert result["candidates"][0]["line"] == 2
            assert result["candidates"][0]["artist"] == "Harry Styles"
            assert result["candidates"][0]["title"] == "As It Was"
            assert result["candidates"][1]["artist"] == "Shania Twain"
            assert result["low_confidence_count"] == 0
            assert result["ready_for_import"] is True

    def test_parse_text_playlist_reads_semicolon_csv_title_artist(self, app):
        with app.app_context():
            result = automation.parse_text_playlist(
                "title;artist\n"
                "As It Was;Harry Styles\n"
            )

            assert result["candidates"][0]["title"] == "As It Was"
            assert result["candidates"][0]["artist"] == "Harry Styles"

    def test_parse_text_playlist_marks_csv_rows_with_missing_values(self, app):
        with app.app_context():
            result = automation.parse_text_playlist(
                "artist,title\n"
                "Harry Styles,\n"
                ",Man! I Feel Like A Woman!\n"
            )

            assert result["count"] == 2
            assert result["low_confidence_count"] == 2
            assert result["low_confidence"][0]["issues"] == ["missing_title"]
            assert result["low_confidence"][1]["issues"] == ["missing_artist"]

    def test_retry_import_job_requeues_dead_letter_job(self, app):
        with app.app_context():
            user = _create_user()
            queue = ImportQueue()
            app.config["IMPORT_QUEUE"] = queue
            record = ImportJobRecord(
                service_name="spotify",
                item_type="playlist",
                item_id="playlist123",
                priority=5,
                user_id=user.id,
                status="dead_letter",
                attempt_count=3,
                max_attempts=3,
                error_message="manual review required",
                completed_at=datetime.utcnow(),
            )
            db.session.add(record)
            db.session.commit()

            result = automation.retry_import_job(record.id, reset_attempts=True)

            assert result["retried"] is True
            assert result["enqueued"] is True
            assert result["job"]["status"] == "pending"
            assert result["job"]["attempt_count"] == 0
            assert queue.snapshot()[0]["record_id"] == record.id

    def test_resolve_text_playlist_matches_catalog_songs(self, app):
        with app.app_context():
            song = _create_song(title="As It Was", artist="Harry Styles")

            result = automation.resolve_text_playlist("Harry Styles - As It Was")

            assert result["resolved_count"] == 1
            assert result["unresolved_count"] == 0
            assert result["resolved"][0]["song_id"] == song.id
            assert result["ready_for_round"] is True

    def test_resolve_text_playlist_review_preserves_order_and_skips_rows(self, app):
        with app.app_context():
            first = _create_song(title="One", artist="A")
            second = _create_song(title="Two", artist="B")

            result = automation.resolve_text_playlist_review(
                "A - One\nUnknown Song Without Artist\nB - Two",
                review_decisions={2: {"line": 2, "action": "skip"}},
            )

            assert result["resolved_count"] == 2
            assert result["skipped_count"] == 1
            assert result["unresolved_count"] == 0
            assert [item["song_id"] for item in result["resolved"]] == [first.id, second.id]
            assert result["source_positions"][0]["source_line"] == 1
            assert result["source_positions"][1]["source_line"] == 3
            assert result["source_positions"][2]["reason"] == "skipped_by_reviewer"

    def test_resolve_text_playlist_review_edits_and_replaces_rows(self, app):
        with app.app_context():
            edited = _create_song(title="Edited Title", artist="Edited Artist")
            replacement = _create_song(title="Replacement", artist="Catalog Artist")

            result = automation.resolve_text_playlist_review(
                "Missing Artist Title\nUnknown - Missing",
                review_decisions={
                    1: {
                        "line": 1,
                        "action": "edit",
                        "artist": "Edited Artist",
                        "title": "Edited Title",
                    },
                    2: {
                        "line": 2,
                        "action": "replace",
                        "song_id": replacement.id,
                    },
                },
            )

            assert result["resolved_count"] == 2
            assert result["unresolved_count"] == 0
            assert [item["song_id"] for item in result["resolved"]] == [edited.id, replacement.id]
            assert result["summary"]["edited_count"] == 1
            assert result["summary"]["replaced_count"] == 1

    def test_resolve_text_playlist_review_requires_explicit_low_confidence_action(self, app):
        with app.app_context():
            _create_song(title="Mystery Song Without Artist", artist="Known Artist")

            result = automation.resolve_text_playlist_review("Mystery Song Without Artist")

            assert result["resolved_count"] == 0
            assert result["unresolved_count"] == 1
            assert "review_required" in result["unresolved"][0]["issues"]

    def test_create_round_from_text_playlist_requires_exact_count(self, app):
        with app.app_context():
            user = _create_user(username="textowner", email="textowner@example.test")
            _create_song(title="One", artist="A")
            _create_song(title="Two", artist="B")

            result = automation.create_round_from_text_playlist(
                "A - One\nB - Two",
                name="Text Round",
                count=2,
                user_id=user.id,
            )

            assert result["created"] is True
            assert result["round"]["name"] == "Text Round"
            assert result["round"]["owner_user_id"] == user.id
            assert result["round"]["song_ids"]

    def test_create_round_from_text_playlist_returns_review_payload(self, app):
        with app.app_context():
            _create_song(title="One", artist="A")

            with pytest.raises(automation.AutomationError) as exc_info:
                automation.create_round_from_text_playlist(
                    "A - One\nUnknown - Missing",
                    count=2,
                )

            assert exc_info.value.details["status"] == "needs_review"
            assert exc_info.value.details["resolution"]["unresolved_count"] == 1

    def test_round_analytics_summary_reports_catalog_health(self, app):
        with app.app_context():
            user = _create_user(username="analytics-master", email="analytics@example.test")
            used_song = _create_song(title="Used", artist="A", genre="Rock", used_count=4)
            _create_song(title="Unused", artist="B", genre="Pop", used_count=0)
            _create_song(title="No Preview", artist="C", genre="Rock")
            _create_song(title="Unknown Genre", artist="D", genre="Unknown", preview_url="https://example.test/unknown.mp3")
            _create_song(title="Spaced Genre", artist="E", genre=" rock ", used_count=0)
            _create_song(title="Blank Genre", artist="F", genre="   ", used_count=0)
            round_id = automation.create_round(
                name="Analytics Used Round",
                round_type="theme",
                criteria="Rock Night",
                song_ids=[used_song.id],
                user_id=user.id,
            )["round"]["id"]
            round_obj = db.session.get(Round, round_id)
            round_obj.round_criteria_used = "Rock Night"
            db.session.commit()

            result = automation.round_analytics_summary(months=6, limit=5, repeat_threshold=3)

            assert result["song_count"] == 6
            assert result["repeat_threshold"] == 3
            assert result["missing_preview_count"] == 5
            assert result["unknown_genre_count"] == 2
            assert result["genre_counts"]["Rock"] == 3
            assert "Unknown" not in result["genre_counts"]
            assert result["most_used_songs"][0]["title"] == "Used"
            assert result["most_used_songs"][0]["above_repeat_threshold"] is True
            assert result["most_used_songs"][0]["affected_rounds"][0]["id"]
            assert result["most_used_songs"][0]["last_used_quizmaster"]["username"] == "analytics-master"
            assert result["most_used_artists"][0]["artist"] == "A"
            assert result["decade_counts"][0]["decade"] == "Unknown"
            assert result["theme_counts"][0]["theme"] == "Rock Night"
            assert result["fatigue_alerts"][0]["title"] == "Used"
            assert any(song["title"] == "Unused" for song in result["unused_candidates"])

    def test_recent_usage_summary_warns_for_recently_used_selected_songs(self, app):
        with app.app_context():
            user = _create_user()
            recent_song = _create_song(
                title="Repeated",
                artist="Artist",
                used_count=4,
            )
            old_song = _create_song(title="Old", artist="Artist", used_count=1)
            recent_song.last_used = datetime.utcnow() - timedelta(days=10)
            old_song.last_used = datetime.utcnow() - timedelta(days=200)
            db.session.commit()
            automation.create_round(
                name="Recent Same Quizmaster",
                round_type="manual",
                song_ids=[recent_song.id],
                user_id=user.id,
            )

            result = automation.recent_usage_summary(
                user_id=user.id,
                months=3,
                song_ids=[recent_song.id, old_song.id],
                repeat_cooldown_weeks=12,
            )

            assert result["selected_song_warnings"][0]["song"]["id"] == recent_song.id
            assert "Repeated" in result["selected_song_warnings"][0]["warning"]
            assert result["selected_song_warnings"][0]["scope"] == "same_quizmaster"
            assert result["selected_song_warnings"][0]["same_quizmaster_repeat"] is True
            assert result["same_quizmaster_round_count"] == 1
            assert result["repeat_cooldown_weeks"] == 12
            assert all(
                warning["song"]["id"] != old_song.id
                for warning in result["selected_song_warnings"]
            )

    def test_seed_source_registry_records_runs(self, app):
        with app.app_context():
            registered = automation.register_seed_source(
                name="Graspop headliners",
                source_type="festival",
                provider="manual",
                url="https://example.test/graspop",
                cadence="annual",
                priority=20,
                notes="Metal and rock headliner source",
            )
            source_id = registered["seed_source"]["id"]
            run = automation.record_seed_source_run(
                source_id,
                status="success",
                songs_seen=120,
                songs_imported=80,
                notes="Initial registry smoke",
            )
            listed = automation.list_seed_sources(source_type="festival", include_runs=True)

            assert registered["created"] is True
            assert run["run"]["songs_imported"] == 80
            assert listed["count"] == 1
            assert listed["sources"][0]["name"] == "Graspop headliners"
            assert listed["sources"][0]["latest_run"]["status"] == "success"
            assert listed["sources"][0]["runs"][0]["songs_seen"] == 120
            assert SeedSource.query.count() == 1
            assert SeedSourceRun.query.count() == 1

    def test_seed_source_registry_updates_existing_source(self, app):
        with app.app_context():
            first = automation.register_seed_source(
                name="Billboard Hot 100",
                source_type="chart",
                provider="billboard",
                priority=10,
            )
            second = automation.register_seed_source(
                name="Billboard Hot 100",
                source_type="chart",
                provider="billboard",
                priority=5,
                active=False,
            )

            assert first["created"] is True
            assert second["created"] is False
            assert second["seed_source"]["priority"] == 5
            assert second["seed_source"]["active"] is False
            assert SeedSource.query.count() == 1

    def test_seed_default_seed_sources_is_idempotent_and_covers_core_sources(self, app):
        with app.app_context():
            first = automation.seed_default_seed_sources()
            second = automation.seed_default_seed_sources()
            listed = automation.list_seed_sources(active=True, limit=50)

            names = {source["name"] for source in listed["sources"]}
            source_types = {source["source_type"] for source in listed["sources"]}
            providers = {source["provider"] for source in listed["sources"]}

            assert first["count"] >= 10
            assert first["created_count"] == first["count"]
            assert second["created_count"] == 0
            assert second["updated_count"] == second["count"]
            assert "Billboard Hot 100" in names
            assert "Offizielle Deutsche Charts Singles" in names
            assert "Graspop Metal Meeting Line-Up" in names
            assert "Wacken Open Air Line-Up" in names
            assert {"chart", "festival"}.issubset(source_types)
            assert {"billboard", "graspop", "wacken"}.issubset(providers)
            assert SeedSource.query.count() == first["count"]

    def test_fetch_seed_source_candidates_from_manual_text_records_read_only_run(self, app):
        with app.app_context():
            source = automation.register_seed_source(
                name="Manual festival list",
                source_type="festival",
                provider="manual",
            )["seed_source"]

            result = automation.fetch_seed_source_candidates(
                source["id"],
                text="Electric Callboy - Hypa Hypa\nMammoth WVH - Another Celebration",
            )

            assert result["ok"] is True
            assert result["imported"] is False
            assert result["count"] == 2
            assert result["candidates"][0]["artist"] == "Electric Callboy"
            assert result["candidates"][0]["title"] == "Hypa Hypa"
            assert result["run"]["status"] == "success"
            assert result["run"]["songs_seen"] == 2
            assert result["run"]["songs_imported"] == 0
            assert SeedSourceRun.query.count() == 1

    def test_fetch_seed_source_candidates_reads_json_payload(self, app):
        with app.app_context():
            source = automation.register_seed_source(
                name="Chart JSON",
                source_type="chart",
                provider="example",
                url="https://example.test/chart.json",
            )["seed_source"]

            response = type("Response", (), {})()
            response.status_code = 200
            response.headers = {"content-type": "application/json"}
            response.text = (
                '{"tracks": ['
                '{"artist": "Chappell Roan", "title": "Good Luck, Babe!"},'
                '{"artist_name": "Sabrina Carpenter", "track_title": "Espresso"}'
                ']}'
            )

            with patch("musicround.services.automation.requests.get", return_value=response) as mock_get:
                result = automation.fetch_seed_source_candidates(source["id"], limit=10)

            mock_get.assert_called_once_with("https://example.test/chart.json", timeout=20.0)
            assert result["count"] == 2
            assert [item["artist"] for item in result["candidates"]] == [
                "Chappell Roan",
                "Sabrina Carpenter",
            ]
            assert result["ready_for_import"] is True

    def test_fetch_seed_source_candidates_hides_provider_fetch_error_body(self, app):
        with app.app_context():
            source = automation.register_seed_source(
                name="Broken chart",
                source_type="chart",
                provider="example",
                url="https://example.test/private-token-chart",
            )["seed_source"]
            response = type("Response", (), {})()
            response.status_code = 500
            response.headers = {"content-type": "text/plain"}
            response.text = "provider-secret-token traceback"

            with patch("musicround.services.automation.requests.get", return_value=response):
                with pytest.raises(automation.AutomationError) as exc_info:
                    automation.fetch_seed_source_candidates(source["id"])

            assert str(exc_info.value) == automation.AUTOMATION_SEED_SOURCE_FETCH_ERROR
            run = SeedSourceRun.query.one()
            assert run.status == "failed"
            assert run.error_message == automation.AUTOMATION_SEED_SOURCE_FETCH_ERROR
            assert "provider-secret-token" not in run.error_message

    def test_quizmaster_context_includes_preferences_and_recent_usage(self, app):
        with app.app_context():
            user = _create_user(username="christian", email="christian@example.test")
            user.first_name = "Christian"
            preferences = UserPreferences(
                user=user,
                default_tts_service="elevenlabs",
                default_language="de",
                tone="dry, seasonal, pub-friendly",
                tts_voice="Rachel",
                email_recipient="host@example.test",
                preferred_genres=json.dumps(["Rock", "Pop"]),
                preferred_decades="1980s, 1990s",
                banned_artists="Banned Artist",
                banned_songs="Banned Song",
                repeat_cooldown_weeks=16,
                enable_intro=True,
                theme="dark",
            )
            db.session.add(preferences)
            db.session.commit()

            result = automation.quizmaster_context(user.id)

            assert result["quizmaster"]["username"] == "christian"
            assert result["quizmaster"]["name"] == "Christian"
            assert result["preferences"]["default_tts_service"] == "elevenlabs"
            assert result["preferences"]["default_language"] == "de"
            assert result["preferences"]["tone"] == "dry, seasonal, pub-friendly"
            assert result["preferences"]["tts_voice"] == "Rachel"
            assert result["preferences"]["email_recipient"] == "host@example.test"
            assert result["preferences"]["preferred_genres"] == ["Rock", "Pop"]
            assert result["preferences"]["preferred_decades"] == ["1980s", "1990s"]
            assert result["preferences"]["banned_artists"] == ["Banned Artist"]
            assert result["preferences"]["banned_songs"] == ["Banned Song"]
            assert result["preferences"]["repeat_cooldown_weeks"] == 16
            assert result["preferences"]["theme"] == "dark"
            assert result["recent_usage"]["window_months"] == 3
            assert result["recent_usage"]["repeat_cooldown_weeks"] == 16

    def test_round_planning_brief_returns_constraints_and_seasonal_notes(self, app):
        with app.app_context():
            user = _create_user()

            result = automation.round_planning_brief(
                user_id=user.id,
                quiz_date="2026-07-09T19:00:00+02:00",
                theme="festival headliners",
                language="German",
                audience="pub quiz regulars",
                difficulty="medium",
                mood="summer rock night",
                must_include=["Electric Callboy", "Def Leppard"],
                avoid=["recent repeats"],
                notes="Lean humorous, but keep answers fair.",
            )

            assert result["theme"] == "festival headliners"
            assert result["brief"]["theme"] == "festival headliners"
            assert result["brief"]["language"] == "German"
            assert result["brief"]["audience"] == "pub quiz regulars"
            assert result["brief"]["difficulty"] == "medium"
            assert result["brief"]["mood"] == "summer rock night"
            assert result["brief"]["must_include"] == ["Electric Callboy", "Def Leppard"]
            assert result["brief"]["avoid"] == ["recent repeats"]
            assert result["brief"]["notes"] == "Lean humorous, but keep answers fair."
            assert result["desired_song_count"] == 8
            assert any("exactly 8 songs" in item for item in result["constraints"])
            assert any("German" in item for item in result["constraints"])
            assert any("Electric Callboy" in item for item in result["constraints"])
            assert any("summer" in item for item in result["date_notes"])
            assert result["round_planning_context"]["brief"] == result["brief"]
            assert result["round_planning_context"]["recent_usage"]["window_months"] == 3
            assert any("User notes" in item for item in result["planning_notes"])
            assert any(
                "rejection_guidance" in item
                for item in result["constraint_explanations"]
            )
            assert {"song_count", "preview_quality", "recent_usage"}.issubset(
                {item["key"] for item in result["constraint_explanations"]}
            )
            assert "agent_prompt" in result

    def test_round_planning_brief_normalizes_single_item_constraints(self, app):
        with app.app_context():
            user = _create_user(username="agent", email="agent@example.test")

            result = automation.round_planning_brief(
                user_id=user.id,
                theme="  one hit wonders  ",
                must_include="  Nena - 99 Luftballons  ",
                avoid="  no schlager repeats  ",
                desired_song_count=10,
            )

            assert result["brief"]["theme"] == "one hit wonders"
            assert result["brief"]["must_include"] == ["Nena - 99 Luftballons"]
            assert result["brief"]["avoid"] == ["no schlager repeats"]
            assert result["brief"]["desired_song_count"] == 10
            assert result["round_planning_context"]["quizmaster_context"]["quizmaster"]["username"] == "agent"
            assert any(
                explanation["key"] == "must_include"
                for explanation in result["round_planning_context"]["constraint_explanations"]
            )

    def test_round_planning_brief_uses_quizmaster_profile_defaults(self, app):
        with app.app_context():
            user = _create_user(username="profile-agent", email="profile@example.test")
            db.session.add(
                UserPreferences(
                    user=user,
                    default_language="en",
                    tone="wry and late-summer",
                    preferred_genres="Rock\nCountry",
                    preferred_decades=json.dumps(["1980s", "2000s"]),
                    banned_artists="Banned Artist",
                    banned_songs="Banned Song",
                    default_tts_service="elevenlabs",
                    tts_voice="Adam",
                    repeat_cooldown_weeks=20,
                )
            )
            db.session.commit()

            result = automation.round_planning_brief(
                user_id=user.id,
                theme="road trip",
            )

            assert result["brief"]["language"] == "en"
            assert result["brief"]["mood"] == "wry and late-summer"
            assert "artist: Banned Artist" in result["brief"]["avoid"]
            assert "song: Banned Song" in result["brief"]["avoid"]
            assert result["brief"]["profile_preferences"]["preferred_genres"] == ["Rock", "Country"]
            assert result["brief"]["profile_preferences"]["preferred_decades"] == ["1980s", "2000s"]
            assert result["brief"]["profile_preferences"]["tts"] == {
                "provider": "elevenlabs",
                "voice": "Adam",
            }
            assert any("Rock; Country" in note for note in result["planning_notes"])
            assert result["round_planning_context"]["recent_usage"]["repeat_cooldown_weeks"] == 20

    def test_planned_quiz_round_lifecycle(self, app):
        with app.app_context():
            user = _create_user(username="planner", email="planner@example.test")
            song = _create_song(title="As It Was", artist="Harry Styles")
            round_id = automation.create_round(
                name="Planned Round",
                round_type="manual",
                song_ids=[song.id],
                user_id=user.id,
            )["round"]["id"]
            _approve_round(round_id, reviewer=user)
            export = RoundExport(
                round_id=round_id,
                user_id=user.id,
                export_type="email",
                destination="planner@example.test",
                status="scheduled",
                scheduled_for=datetime(2026, 7, 9, 17, 0),
            )
            db.session.add(export)
            db.session.commit()

            created = automation.create_planned_quiz_round(
                quiz_date="2026-07-09T19:00:00+02:00",
                quizmaster_id=user.id,
                theme="festival headliners",
                brief="Build eight robust songs.",
                due_at="2026-07-09T17:00:00+02:00",
                source_playlist_url="https://open.spotify.com/playlist/example",
            )
            plan_id = created["plan"]["id"]
            listed = automation.list_planned_quiz_rounds(quizmaster_id=user.id)
            linked = automation.link_planned_quiz_round(
                plan_id,
                round_id=round_id,
                export_id=export.id,
                status="scheduled",
            )

            assert created["created"] is True
            assert created["plan"]["quiz_date"] == "2026-07-09T17:00:00Z"
            assert created["plan"]["due_at"] == "2026-07-09T15:00:00Z"
            assert created["plan"]["missing_deliverables"] == [
                "round",
                "approved_round",
                "scheduled_email",
            ]
            assert listed["count"] == 1
            assert listed["missing_deliverable_count"] == 1
            assert linked["plan"]["round_id"] == round_id
            assert linked["plan"]["export_id"] == export.id
            assert linked["plan"]["status"] == "scheduled"
            assert linked["plan"]["deliverable_status"]["complete"] is True
            assert PlannedQuizRound.query.get(plan_id).round_id == round_id

    def test_planned_quiz_round_rejects_invalid_links(self, app):
        with app.app_context():
            user = _create_user()
            created = automation.create_planned_quiz_round(
                quiz_date="2026-07-09T19:00:00+02:00",
                quizmaster_id=user.id,
            )

            with pytest.raises(automation.AutomationError) as exc_info:
                automation.link_planned_quiz_round(created["plan"]["id"], round_id=9999)

            assert "Round 9999 was not found" in str(exc_info.value)

    def test_planned_quiz_round_can_be_unassigned(self, app):
        with app.app_context():
            _create_user(username="planner-a", email="planner-a@example.test")
            _create_user(username="planner-b", email="planner-b@example.test")

            created = automation.create_planned_quiz_round(
                quiz_date="2026-07-09T19:00:00+02:00",
                theme="unassigned production slot",
            )

            assert created["created"] is True
            assert created["plan"]["quizmaster_id"] is None
            assert created["plan"]["quizmaster"] is None

    def test_planned_quiz_round_flags_due_missing_deliverables(self, app):
        with app.app_context():
            due_at = datetime.utcnow() + timedelta(hours=12)
            quiz_date = due_at + timedelta(hours=2)

            created = automation.create_planned_quiz_round(
                quiz_date=quiz_date,
                due_at=due_at,
                status="blocked",
            )
            listed = automation.list_planned_quiz_rounds(status="blocked")

            assert created["plan"]["due_warning"] is True
            assert created["plan"]["blocked_close_to_due"] is True
            assert created["plan"]["deliverable_status"]["needs_round"] is True
            assert created["plan"]["deliverable_status"]["needs_scheduled_email"] is True
            assert listed["due_warning_count"] == 1

    def test_draft_round_audio_scripts_uses_round_context(self, app):
        with app.app_context():
            user = _create_user()
            db.session.add(
                UserPreferences(
                    user=user,
                    default_language="en",
                    tone="playful but precise",
                    default_tts_service="elevenlabs",
                    tts_voice="Rachel",
                )
            )
            db.session.commit()
            song = _create_song(title="As It Was", artist="Harry Styles")
            round_id = automation.create_round(
                name="Pop Night",
                round_type="manual",
                song_ids=[song.id],
            )["round"]["id"]

            result = automation.draft_round_audio_scripts(
                round_id=round_id,
                user_id=user.id,
                quiz_date="2026-07-09T19:00:00+02:00",
            )

            assert result["round_name"] == "Pop Night"
            assert "Harry Styles" in result["scripts"]["intro"]
            assert "playful but precise" in result["scripts"]["intro"]
            assert result["tone"] == "playful but precise"
            assert result["language"] == "en"
            assert result["tts"] == {"provider": "elevenlabs", "voice": "Rachel"}
            assert "second listen" in result["scripts"]["replay"]
            assert result["next_step"].startswith("Review the text")

    def test_draft_round_audio_scripts_can_persist_review_records(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="Wildflowers", artist="Tom Petty")
            round_id = automation.create_round(
                name="Warm Round",
                round_type="manual",
                song_ids=[song.id],
                user_id=user.id,
            )["round"]["id"]

            result = automation.draft_round_audio_scripts(
                round_id=round_id,
                user_id=user.id,
                theme="comfort songs",
                persist=True,
            )

            assert len(result["script_records"]) == 3
            assert RoundAudioScript.query.filter_by(round_id=round_id).count() == 3
            assert result["script_records"][0]["status"] == "draft"
            assert "generate_tts_from_script" in result["next_step"]

    def test_draft_round_track_hints_can_persist_positioned_records(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(
                title="Secret Song",
                artist="Known Artist",
                genre="Rock",
                year=1994,
            )
            round_id = automation.create_round(
                name="Hinted",
                round_type="manual",
                song_ids=[song.id],
                user_id=user.id,
            )["round"]["id"]

            result = automation.draft_round_track_hints(
                round_id=round_id,
                user_id=user.id,
                persist=True,
            )

            assert len(result["hints"]) == 1
            assert result["hints"][0]["position"] == 1
            assert "1994" in result["hints"][0]["text"]
            assert "Secret Song" not in result["hints"][0]["text"]
            assert result["script_records"][0]["script_type"] == "track_hint"
            assert result["script_records"][0]["cue_position"] == 1

    def test_save_round_track_hints_validates_positions(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="One", artist="Artist")
            round_id = automation.create_round(
                name="Hint Positions",
                round_type="manual",
                song_ids=[song.id],
                user_id=user.id,
            )["round"]["id"]

            with pytest.raises(automation.AutomationError, match="outside this round"):
                automation.save_round_track_hints(
                    round_id=round_id,
                    user_id=user.id,
                    hints=[{"position": 2, "text": "Too far"}],
                )

    def test_round_audio_script_review_and_tts_generation(self, app):
        with app.app_context():
            user = _create_user()
            song = _create_song(title="Intro", artist="Artist")
            round_id = automation.create_round(
                name="Scripted",
                round_type="manual",
                song_ids=[song.id],
                user_id=user.id,
            )["round"]["id"]
            saved = automation.save_round_audio_scripts(
                round_id,
                user_id=user.id,
                scripts={"intro": "Welcome to the scripted round"},
                status="draft",
            )
            script_id = saved["scripts"][0]["id"]

            updated = automation.update_round_audio_script(
                script_id,
                text="Welcome to the approved scripted round",
                status="approved",
                selected=True,
            )
            listed = automation.list_round_audio_scripts(round_id=round_id, status="approved")

            with patch("musicround.services.automation.generate_tts_mp3") as mock_tts:
                mock_tts.return_value = "custommp3/agentuser/intro.mp3"
                generated = automation.generate_tts_from_script(script_id, service="openai")

            assert updated["script"]["status"] == "approved"
            assert listed["count"] == 1
            assert generated["script"]["status"] == "used"
            assert generated["generated"]["path"] == "custommp3/agentuser/intro.mp3"
            assert User.query.get(user.id).intro_mp3 == "custommp3/agentuser/intro.mp3"

    def test_track_hint_tts_generation_stores_script_path_without_overwriting_intro(self, app):
        with app.app_context():
            user = _create_user()
            user.intro_mp3 = "custommp3/agentuser/existing-intro.mp3"
            song = _create_song(title="Hint", artist="Artist")
            round_id = automation.create_round(
                name="Hinted TTS",
                round_type="manual",
                song_ids=[song.id],
                user_id=user.id,
            )["round"]["id"]
            saved = automation.save_round_track_hints(
                round_id=round_id,
                user_id=user.id,
                hints=[{"position": 1, "text": "This is the hint."}],
                status="approved",
            )
            script_id = saved["scripts"][0]["id"]

            with patch("musicround.services.automation.generate_tts_mp3") as mock_tts:
                mock_tts.return_value = "custommp3/agentuser/round_1_hint_1.mp3"
                generated = automation.generate_tts_from_script(script_id, service="openai")

            assert generated["script"]["status"] == "used"
            assert generated["generated"]["mp3_type"] == "track_hint"
            assert generated["generated"]["path"].endswith("round_1_hint_1.mp3")
            assert User.query.get(user.id).intro_mp3 == "custommp3/agentuser/existing-intro.mp3"
