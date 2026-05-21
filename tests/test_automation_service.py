"""Tests for agent automation services."""

import os
import shutil
import tempfile
from unittest.mock import patch

import pytest

from musicround.models import Song, User, db
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
            _create_song(title="Blue Monday", artist="New Order", genre="Synthpop")

            result = automation.find_songs(query="blue")

            assert result["count"] == 1
            assert result["songs"][0]["title"] == "Blue Monday"

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
