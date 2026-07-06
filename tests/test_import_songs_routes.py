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


def _login_user_without_spotify_token(client):
    user = User(username='manualimporter', email='manualimporter@example.com')
    user.password = 'ImportPass123!'
    db.session.add(user)
    db.session.commit()

    client.post('/users/login', data={
        'username': 'manualimporter',
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

    def test_spotify_track_import_passes_resolved_manual_token(self, app, client, monkeypatch):
        """The route must pass the token accepted by its Spotify token gate into ImportHelper."""
        from musicround.routes import import_songs

        captured = {}

        def fake_import_item(**kwargs):
            captured.update(kwargs)
            return {'imported_count': 1, 'skipped_count': 0, 'error_count': 0, 'errors': []}

        with app.app_context():
            _login_user_without_spotify_token(client)

        monkeypatch.setattr(import_songs, 'get_spotify_token', lambda: ('manual-token', 'manual'))
        monkeypatch.setattr(import_songs.oauth, 'spotify', object(), raising=False)
        monkeypatch.setattr(import_songs.ImportHelper, 'import_item', fake_import_item)

        response = client.post('/import/song', data={'song_id': 'spotify-track-1'})

        assert response.status_code == 302
        assert captured['service_name'] == 'spotify'
        assert captured['item_type'] == 'track'
        assert captured['item_id'] == 'spotify-track-1'
        assert captured['spotify_token'] == 'manual-token'

    def test_spotify_playlist_queue_passes_resolved_manual_token(self, app, client, monkeypatch):
        """Queued playlist imports must retain the manual token accepted by the route gate."""
        from musicround.routes import import_songs

        captured = {}

        class FakeJob:
            id = 42

        def fake_enqueue_import_job(**kwargs):
            captured.update(kwargs)
            return FakeJob()

        with app.app_context():
            _login_user_without_spotify_token(client)

        monkeypatch.setattr(import_songs, 'get_spotify_token', lambda: ('manual-token', 'manual'))
        monkeypatch.setitem(app.config, 'import_queue', object())
        monkeypatch.setattr(
            'musicround.helpers.import_queue.enqueue_import_job',
            fake_enqueue_import_job,
        )

        response = client.post('/import/playlist', data={'playlist_id': 'playlist-123'})

        assert response.status_code == 302
        assert captured['service_name'] == 'spotify'
        assert captured['item_type'] == 'playlist'
        assert captured['item_id'] == 'playlist-123'
        assert captured['spotify_token'] == 'manual-token'

    def test_direct_playlist_browser_error_hides_provider_details(self, app, client, monkeypatch):
        """Direct playlist browser failures must not render provider or token details."""
        from musicround.helpers import spotify_direct

        class FailingDirectClient:
            def __init__(self, bearer_token):
                self.bearer_token = bearer_token

            def fetch_all_user_playlists(self, account):
                raise RuntimeError(
                    'invalid_token bearer-token-fragment provider traceback'
                )

        with app.app_context():
            _login_user_without_spotify_token(client)

        with client.session_transaction() as sess:
            sess['direct_bearer_token'] = 'bearer-token-fragment'

        monkeypatch.setattr(spotify_direct, 'SpotifyDirectClient', FailingDirectClient)

        response = client.get('/import/direct-official-playlists', follow_redirects=True)

        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert (
            'Error retrieving playlists from Spotify. '
            'Please refresh your Spotify token and try again.'
        ) in body
        assert 'invalid_token' not in body
        assert 'bearer-token-fragment' not in body
        assert 'provider traceback' not in body
