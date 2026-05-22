"""Tests for agent automation services."""

import os
import shutil
import tempfile
from unittest.mock import patch

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only")
os.environ.setdefault("AUTOMATION_TOKEN", "test-automation-token-for-testing")

from musicround.models import Song, SongTag, Tag, User, db
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
