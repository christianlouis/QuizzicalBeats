"""Tests for unified import helper behavior."""
from datetime import datetime, timedelta

from flask_login import login_user

from musicround.helpers.import_helper import ImportHelper
from musicround.models import Song, SystemSetting, User, db


class DeezerPlaylistStub:
    """Minimal Deezer client stub for playlist import result contracts."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def import_playlist(self, playlist_id, lastfm_api_key=None):
        self.calls.append((playlist_id, lastfm_api_key))
        return self.result


class FailingDeezerTrackStub:
    """Deezer client stub that fails during track import."""

    def import_track(self, track_id, lastfm_api_key=None):
        raise RuntimeError(f'Deezer unavailable for {track_id}')


class FakeSpotifyResponse:
    """Minimal response object for Authlib-style Spotify client calls."""

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSpotifyClient:
    """Spotify client stub that records the token used for each call."""

    token = None

    def __init__(self):
        self.calls = []

    def get(self, path, token=None):
        self.calls.append((path, token))
        if path == 'tracks/spotify-track-1':
            return FakeSpotifyResponse({
                'id': 'spotify-track-1',
                'name': 'Fallback Track',
                'artists': [{'name': 'Reliable Artist'}],
                'album': {
                    'name': 'Reliable Album',
                    'release_date': '1999-01-01',
                    'images': [{'url': 'https://example.com/cover.jpg'}],
                },
                'external_ids': {},
                'preview_url': 'https://example.com/preview.mp3',
                'popularity': 80,
            })
        if path == 'audio-features/spotify-track-1':
            return FakeSpotifyResponse({
                'danceability': 0.5,
                'energy': 0.7,
                'duration_ms': 240000,
            })
        raise AssertionError(f'Unexpected Spotify path: {path}')


class TestImportHelperDeezer:
    """Tests for Deezer import result handling."""

    def test_deezer_playlist_uses_reported_import_and_skip_counts(self, app):
        """Playlist imports must report DeezerClient's actual counters."""
        result = {
            'imported_songs': ['song-a', 'song-b'],
            'skipped_songs': ['duplicate-a'],
            'imported_count': 2,
            'skipped_count': 1,
            'song_ids': [10, 11, 12],
        }
        deezer = DeezerPlaylistStub(result)

        with app.app_context():
            app.config['deezer'] = deezer
            app.config['LASTFM_API_KEY'] = 'lastfm-test-key'

            response = ImportHelper.import_item('deezer', 'playlist', 'playlist-123')

        assert response == {
            'imported_count': 2,
            'skipped_count': 1,
            'error_count': 0,
            'errors': [],
            'song_ids': [10, 11, 12],
        }
        assert deezer.calls == [('playlist-123', 'lastfm-test-key')]

    def test_deezer_playlist_empty_counts_return_error(self, app):
        """An empty Deezer playlist result should be treated as no songs found."""
        deezer = DeezerPlaylistStub({
            'imported_songs': [],
            'skipped_songs': [],
            'imported_count': 0,
            'skipped_count': 0,
        })

        with app.app_context():
            app.config['deezer'] = deezer

            response = ImportHelper.import_item('deezer', 'playlist', 'playlist-empty')

        assert response['imported_count'] == 0
        assert response['skipped_count'] == 0
        assert response['error_count'] == 1
        assert 'No songs found in Deezer playlist playlist-empty' in response['errors'][0]

    def test_deezer_track_exception_returns_structured_error(self, app):
        """Track imports should report Deezer client failures without raising."""
        with app.app_context():
            app.config['deezer'] = FailingDeezerTrackStub()
            app.config['LASTFM_API_KEY'] = 'lastfm-test-key'

            response = ImportHelper.import_item('deezer', 'track', 'track-err')

        assert response == {
            'imported_count': 0,
            'skipped_count': 0,
            'error_count': 1,
            'errors': ['Failed to import Deezer track track-err: Deezer unavailable for track-err'],
        }


class TestImportHelperSpotifyTokens:
    """Regression tests for the Spotify token resolution cascade."""

    def test_spotify_track_import_uses_manual_session_token(self, app):
        """Manual bearer tokens must reach the actual Spotify import call."""
        spotify = FakeSpotifyClient()

        with app.test_request_context():
            from flask import session

            session['access_token'] = 'manual-token'
            session['bearer_token_added'] = datetime.now().timestamp()

            response = ImportHelper.import_item(
                'spotify',
                'track',
                'spotify-track-1',
                oauth_spotify=spotify,
            )

        assert response['imported_count'] == 1
        assert spotify.calls[0][1]['access_token'] == 'manual-token'

        with app.app_context():
            song = Song.query.filter_by(spotify_id='spotify-track-1').one_or_none()
            assert song is not None
            assert song.title == 'Fallback Track'

    def test_spotify_track_import_uses_system_fallback_token(self, app):
        """System fallback tokens must work when no user token exists."""
        spotify = FakeSpotifyClient()

        with app.test_request_context():
            SystemSetting.set('fallback_spotify_refresh_token', 'system-refresh-token')
            SystemSetting.set('system_spotify_token', 'system-token')
            SystemSetting.set(
                'system_spotify_token_expiry',
                (datetime.now() + timedelta(hours=1)).isoformat(),
            )
            db.session.commit()

            response = ImportHelper.import_item(
                'spotify',
                'track',
                'spotify-track-1',
                oauth_spotify=spotify,
            )

        assert response['imported_count'] == 1
        assert spotify.calls[0][1]['access_token'] == 'system-token'

    def test_explicit_user_spotify_token_keeps_refresh_metadata(self, app):
        """Explicit user tokens must still allow Authlib refresh persistence."""
        expiry = datetime.now() + timedelta(hours=1)

        with app.test_request_context():
            user = User(username='refreshuser', email='refresh@example.com')
            user.password = 'ImportPass123!'
            user.spotify_token = 'user-access-token'
            user.spotify_refresh_token = 'user-refresh-token'
            user.spotify_token_expiry = expiry
            db.session.add(user)
            db.session.commit()
            login_user(user)

            token = ImportHelper._resolve_spotify_auth_token('user-access-token')

        assert token['access_token'] == 'user-access-token'
        assert token['refresh_token'] == 'user-refresh-token'
        assert token['expires_at'] == int(expiry.timestamp())
