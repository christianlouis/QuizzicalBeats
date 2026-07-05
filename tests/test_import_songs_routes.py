"""Tests for manual song import routes."""
from datetime import datetime, timedelta

from musicround.models import Song, User, db


class FakeSpotifyResponse:
    """Minimal response object for Authlib-style Spotify client calls."""

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSpotifyClient:
    """Spotify client stub that returns one importable track."""

    token = None

    def get(self, path, token=None):
        assert path == 'tracks/spotify-track-1'
        return FakeSpotifyResponse({
            'id': 'spotify-track-1',
            'name': 'Committed Track',
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


def _login_spotify_user(client):
    user = User(username='spotifyimporter', email='spotifyimporter@example.com')
    user.password = 'ImportPass123!'
    user.spotify_token = 'spotify-access-token'
    user.spotify_refresh_token = 'spotify-refresh-token'
    user.spotify_token_expiry = datetime.now() + timedelta(hours=1)
    db.session.add(user)
    db.session.commit()

    client.post('/users/login', data={
        'username': 'spotifyimporter',
        'password': 'ImportPass123!',
    })


class TestSpotifySongImportRoute:
    """Regression tests for the single-track Spotify import flow."""

    def test_spotify_track_import_commits_created_song(self, app, client, monkeypatch):
        """A successful single-track import must survive request session cleanup."""
        from musicround.routes import import_songs

        with app.app_context():
            _login_spotify_user(client)

        monkeypatch.setattr(import_songs, 'get_spotify_token', lambda: ('spotify-access-token', 'user'))
        monkeypatch.setattr(import_songs.oauth, 'spotify', FakeSpotifyClient(), raising=False)
        monkeypatch.setattr(
            'musicround.helpers.import_helper.ImportHelper._fetch_audio_features_for_song',
            lambda *args, **kwargs: None,
        )

        response = client.post('/import/song', data={'song_id': 'spotify-track-1'})

        assert response.status_code == 302
        assert response.headers['Location'].endswith('/view-songs')

        with app.app_context():
            db.session.remove()
            song = Song.query.filter_by(spotify_id='spotify-track-1').one_or_none()

        assert song is not None
        assert song.title == 'Committed Track'
        assert song.artist == 'Reliable Artist'
