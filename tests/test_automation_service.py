"""Tests for agent automation services."""

import os
import shutil
import tempfile
from unittest.mock import patch

import pytest
from pydub import AudioSegment

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only")
os.environ.setdefault("AUTOMATION_TOKEN", "test-automation-token-for-testing")

from musicround.models import Round, RoundExport, Song, SongTag, Tag, User, db
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


class TestSongAutomation:
    """Tests for catalog lookup and mutation."""

    def test_find_songs_by_query(self, app):
        with app.app_context():
            _create_song(
                title="Blue Monday",
                artist="New Order",
                genre="Synthpop",
                used_count=3,
            )

            result = automation.find_songs(query="blue")

            assert result["count"] == 1
            assert result["songs"][0]["title"] == "Blue Monday"
            assert result["songs"][0]["used_count"] == 3
            assert result["songs"][0]["usage_frequency"] == 3
            assert "last_used" in result["songs"][0]

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

    def test_inspect_round_package_warns_for_mp3_duration_mismatch(self, app):
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
                    return_value={"warnings": [], "ok": True, "duration_seconds": 40},
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
