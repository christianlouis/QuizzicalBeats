"""Tests for musicround.helpers.utils utility functions."""
import pytest
import os
import string
from unittest.mock import patch, MagicMock


class TestGenerateToken:
    """Tests for the generate_token function."""

    def test_returns_string(self):
        """Test that generate_token returns a string."""
        from musicround.helpers.utils import generate_token
        token = generate_token()
        assert isinstance(token, str)

    def test_default_length(self):
        """Test that the default token length is 32."""
        from musicround.helpers.utils import generate_token
        token = generate_token()
        assert len(token) == 32

    def test_custom_length(self):
        """Test that a custom length is respected."""
        from musicround.helpers.utils import generate_token
        for length in (16, 32, 64, 128):
            token = generate_token(length=length)
            assert len(token) == length

    def test_only_alphanumeric(self):
        """Test that the token contains only alphanumeric characters."""
        from musicround.helpers.utils import generate_token
        token = generate_token(length=100)
        allowed = set(string.ascii_letters + string.digits)
        assert all(c in allowed for c in token)

    def test_tokens_are_unique(self):
        """Test that consecutive tokens differ."""
        from musicround.helpers.utils import generate_token
        tokens = {generate_token() for _ in range(10)}
        # With 32-char alphanumeric tokens the collision probability is negligible
        assert len(tokens) == 10


class TestAllowedFile:
    """Tests for the allowed_file function."""

    def test_mp3_is_allowed(self):
        """Test that .mp3 files are allowed."""
        from musicround.helpers.utils import allowed_file
        assert allowed_file('song.mp3') is True

    def test_mp3_uppercase_is_allowed(self):
        """Test that .MP3 (uppercase) files are allowed."""
        from musicround.helpers.utils import allowed_file
        assert allowed_file('song.MP3') is True

    def test_wav_is_not_allowed(self):
        """Test that .wav files are not allowed."""
        from musicround.helpers.utils import allowed_file
        assert allowed_file('song.wav') is False

    def test_pdf_is_not_allowed(self):
        """Test that .pdf files are not allowed."""
        from musicround.helpers.utils import allowed_file
        assert allowed_file('document.pdf') is False

    def test_no_extension_is_not_allowed(self):
        """Test that a filename without an extension is not allowed."""
        from musicround.helpers.utils import allowed_file
        assert allowed_file('noextension') is False

    def test_empty_string_is_not_allowed(self):
        """Test that an empty filename is not allowed."""
        from musicround.helpers.utils import allowed_file
        assert allowed_file('') is False

    def test_dot_only_is_not_allowed(self):
        """Test that a filename that is just a dot is not allowed."""
        from musicround.helpers.utils import allowed_file
        assert allowed_file('.') is False

    def test_mp3_mixed_case_filename(self):
        """Test a mixed-case filename with .mp3 extension."""
        from musicround.helpers.utils import allowed_file
        assert allowed_file('My Great Song.mp3') is True


class TestGetAvailableVoices:
    """Tests for the get_available_voices function."""

    def test_polly_returns_list(self, app):
        """Test that polly service returns a non-empty list."""
        from musicround.helpers.utils import get_available_voices
        voices = get_available_voices(service='polly')
        assert isinstance(voices, list)
        assert len(voices) > 0

    def test_polly_voice_structure(self, app):
        """Test that each polly voice has the required keys."""
        from musicround.helpers.utils import get_available_voices
        voices = get_available_voices(service='polly')
        for voice in voices:
            assert 'id' in voice
            assert 'name' in voice
            assert 'gender' in voice
            assert 'language' in voice

    def test_polly_includes_joanna(self, app):
        """Test that the Joanna voice is included in polly voices."""
        from musicround.helpers.utils import get_available_voices
        voices = get_available_voices(service='polly')
        ids = [v['id'] for v in voices]
        assert 'Joanna' in ids

    def test_openai_returns_list(self, app):
        """Test that openai service returns a non-empty list."""
        from musicround.helpers.utils import get_available_voices
        voices = get_available_voices(service='openai')
        assert isinstance(voices, list)
        assert len(voices) > 0

    def test_openai_voice_structure(self, app):
        """Test that each openai voice has the required keys."""
        from musicround.helpers.utils import get_available_voices
        voices = get_available_voices(service='openai')
        for voice in voices:
            assert 'id' in voice
            assert 'name' in voice

    def test_openai_includes_alloy(self, app):
        """Test that the alloy voice is included in openai voices."""
        from musicround.helpers.utils import get_available_voices
        voices = get_available_voices(service='openai')
        ids = [v['id'] for v in voices]
        assert 'alloy' in ids

    def test_elevenlabs_no_api_key_returns_empty(self, app):
        """Test that elevenlabs without API key returns empty list."""
        from musicround.helpers.utils import get_available_voices
        # The test app has no ElevenLabs API key configured
        voices = get_available_voices(service='elevenlabs')
        assert voices == []

    def test_unknown_service_returns_empty(self, app):
        """Test that an unknown service returns an empty list."""
        from musicround.helpers.utils import get_available_voices
        voices = get_available_voices(service='unknown_service')
        assert voices == []
