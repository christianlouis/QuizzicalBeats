"""Tests for agent automation services."""

import os
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
    RoundAudioScript,
    RoundExport,
    RoundShare,
    SeedSource,
    SeedSourceRun,
    Song,
    SongTag,
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

            shared = automation.share_round(round_id, viewer.id, role="editor")
            listed = automation.list_round_shares(round_id)
            revoked = automation.revoke_round_share(round_id, viewer.id)

            assert shared["created"] is True
            assert shared["share"]["role"] == "editor"
            assert listed["count"] == 1
            assert listed["owner"]["id"] == owner.id
            assert revoked["revoked"] is True
            assert RoundShare.query.count() == 0
            assert db.session.get(Round, round_id).visibility == "private"


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
            assert any(
                issue["code"] == "round_mp3_duration_mismatch"
                for issue in result["issues"]
            )

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
            assert any(
                issue["code"] == "round_mp3_duration_mismatch"
                for issue in result["issues"]
            )

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
                patch("musicround.services.automation.send_email") as mock_send,
            ):
                with pytest.raises(automation.AutomationError, match="quality gate") as exc_info:
                    automation.email_round(round_id, user_id=user.id)

            assert not mock_send.called
            assert exc_info.value.details["status"] == "needs_substitution"
            assert exc_info.value.details["report"]["status"] == "needs_substitution"
            export = RoundExport.query.filter_by(round_id=round_id).one()
            assert export.status == "failed"

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
                    scheduled_for="2026-07-09T19:00:00+02:00",
                    user_id=user.id,
                    subject="Scheduled subject",
                )

            export = RoundExport.query.get(result["export"]["id"])
            assert result["scheduled"] is True
            assert result["quality"]["status"] == "ok"
            assert export.status == "scheduled"
            assert export.destination == user.email
            assert export.subject == "Scheduled subject"
            assert result["export"]["scheduled_for"] == "2026-07-09T17:00:00Z"

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

            with patch("musicround.services.automation.generate_round_assets") as mock_assets:
                with pytest.raises(automation.AutomationError, match="Email configuration") as exc_info:
                    automation.schedule_round_email(
                        round_id,
                        scheduled_for="2026-07-09T19:00:00+02:00",
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
                        scheduled_for="2026-07-09T19:00:00+02:00",
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
            app.config["ROUND_MP3_DIR"] = os.path.join(app.instance_path, "missing-rounds")

            with patch("musicround.services.automation.generate_round_pdf") as mock_pdf:
                with pytest.raises(automation.AutomationError, match="storage") as exc_info:
                    automation.schedule_round_email(
                        round_id,
                        scheduled_for="2026-07-09T19:00:00+02:00",
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
                    scheduled_for="2026-07-09T19:00:00+02:00",
                    user_id=user.id,
                )

            result = automation.list_scheduled_round_emails(user_id=user.id)

            assert result["count"] == 1
            assert result["scheduled_exports"][0]["round_id"] == round_id
            assert result["scheduled_exports"][0]["status"] == "scheduled"

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
                    scheduled_for="2026-07-09T19:00:00+02:00",
                    user_id=user.id,
                )

            with patch(
                "musicround.services.automation.email_round",
                return_value={"success": True, "message": "sent"},
            ) as mock_email:
                result = automation.process_due_scheduled_round_emails(
                    now="2026-07-09T19:01:00+02:00"
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
                    scheduled_for="2026-07-09T19:00:00+02:00",
                    user_id=user.id,
                )

            with patch(
                "musicround.services.automation.email_round",
                side_effect=RuntimeError("smtp-secret token=mail-secret traceback"),
            ):
                result = automation.process_due_scheduled_round_emails(
                    now="2026-07-09T19:01:00+02:00"
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
                    scheduled_for="2026-07-09T19:00:00+02:00",
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
                    now="2026-07-09T19:01:00+02:00"
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
            _create_song(title="Used", artist="A", genre="Rock", used_count=4)
            _create_song(title="Unused", artist="B", genre="Pop", used_count=0)
            _create_song(title="No Preview", artist="C", genre="Rock")
            _create_song(title="Unknown Genre", artist="D", genre="Unknown", preview_url="https://example.test/unknown.mp3")
            _create_song(title="Spaced Genre", artist="E", genre=" rock ", used_count=0)
            _create_song(title="Blank Genre", artist="F", genre="   ", used_count=0)

            result = automation.round_analytics_summary(months=6, limit=5)

            assert result["song_count"] == 6
            assert result["missing_preview_count"] == 5
            assert result["unknown_genre_count"] == 2
            assert result["genre_counts"]["Rock"] == 3
            assert "Unknown" not in result["genre_counts"]
            assert result["most_used_songs"][0]["title"] == "Used"
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

            result = automation.recent_usage_summary(
                user_id=user.id,
                months=3,
                song_ids=[recent_song.id, old_song.id],
            )

            assert result["selected_song_warnings"][0]["song"]["id"] == recent_song.id
            assert "Repeated" in result["selected_song_warnings"][0]["warning"]
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

    def test_quizmaster_context_includes_preferences_and_recent_usage(self, app):
        with app.app_context():
            user = _create_user(username="christian", email="christian@example.test")
            user.first_name = "Christian"
            preferences = UserPreferences(
                user=user,
                default_tts_service="elevenlabs",
                enable_intro=True,
                theme="dark",
            )
            db.session.add(preferences)
            db.session.commit()

            result = automation.quizmaster_context(user.id)

            assert result["quizmaster"]["username"] == "christian"
            assert result["quizmaster"]["name"] == "Christian"
            assert result["preferences"]["default_tts_service"] == "elevenlabs"
            assert result["preferences"]["theme"] == "dark"
            assert result["recent_usage"]["window_months"] == 3

    def test_round_planning_brief_returns_constraints_and_seasonal_notes(self, app):
        with app.app_context():
            user = _create_user()

            result = automation.round_planning_brief(
                user_id=user.id,
                quiz_date="2026-07-09T19:00:00+02:00",
                theme="festival headliners",
            )

            assert result["theme"] == "festival headliners"
            assert result["desired_song_count"] == 8
            assert any("exactly 8 songs" in item for item in result["constraints"])
            assert any("summer" in item for item in result["date_notes"])
            assert "agent_prompt" in result

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
            assert listed["count"] == 1
            assert linked["plan"]["round_id"] == round_id
            assert linked["plan"]["export_id"] == export.id
            assert linked["plan"]["status"] == "scheduled"
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

    def test_draft_round_audio_scripts_uses_round_context(self, app):
        with app.app_context():
            user = _create_user()
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
