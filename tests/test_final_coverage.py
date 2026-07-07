"""Final targeted tests to push coverage to 30%."""
import pytest
from musicround.models import db, User, Song


def _login(app, client, username='final_user', email='final@example.com', is_admin=False):
    """Helper: create and log in a user."""
    with app.app_context():
        existing = User.query.filter_by(username=username).first()
        if not existing:
            user = User(username=username, email=email, is_admin=is_admin)
            user.password = 'FinalPass123!'
            db.session.add(user)
            db.session.commit()
        elif is_admin and not existing.is_admin:
            existing.is_admin = True
            db.session.commit()
    client.post('/users/login', data={'username': username, 'password': 'FinalPass123!'})


class TestFilterPlaylistsByKeywords:
    """Tests for the pure filter_playlists_by_keywords function in import_routes."""

    def test_empty_playlists(self, app):
        """Test filtering an empty list returns empty."""
        with app.app_context():
            from musicround.routes.import_routes import filter_playlists_by_keywords
            result = filter_playlists_by_keywords([], ['hits'])
        assert result == []

    def test_empty_keywords(self, app):
        """Test filtering with no keywords returns no matches."""
        with app.app_context():
            from musicround.routes.import_routes import filter_playlists_by_keywords
            playlists = [{'name': 'Top Hits 2024'}, {'name': 'Chill Vibes'}]
            result = filter_playlists_by_keywords(playlists, [])
        assert result == []

    def test_matching_keyword(self, app):
        """Test filtering by a matching keyword."""
        with app.app_context():
            from musicround.routes.import_routes import filter_playlists_by_keywords
            playlists = [
                {'name': 'Top Hits 2024'},
                {'name': 'Chill Vibes'},
                {'name': 'Greatest Hits Ever'},
            ]
            result = filter_playlists_by_keywords(playlists, ['hits'])
        assert len(result) == 2
        names = [p['name'] for p in result]
        assert 'Top Hits 2024' in names
        assert 'Greatest Hits Ever' in names

    def test_case_insensitive(self, app):
        """Test that filtering is case-insensitive."""
        with app.app_context():
            from musicround.routes.import_routes import filter_playlists_by_keywords
            playlists = [{'name': 'CLASSIC ROCK'}, {'name': 'Modern Pop'}]
            result = filter_playlists_by_keywords(playlists, ['classic'])
        assert len(result) == 1
        assert result[0]['name'] == 'CLASSIC ROCK'

    def test_multiple_keywords(self, app):
        """Test filtering by multiple keywords (OR logic)."""
        with app.app_context():
            from musicround.routes.import_routes import filter_playlists_by_keywords
            playlists = [
                {'name': 'Best of Jazz'},
                {'name': 'Chill Rock'},
                {'name': 'Sunday Morning'},
            ]
            result = filter_playlists_by_keywords(playlists, ['jazz', 'rock'])
        assert len(result) == 2

    def test_debug_info_updated(self, app):
        """Test that debug_info is populated when provided."""
        with app.app_context():
            from musicround.routes.import_routes import filter_playlists_by_keywords
            playlists = [{'name': 'Best Jazz Playlist'}]
            debug_info = {'matched_keywords': {}}
            filter_playlists_by_keywords(playlists, ['jazz'], debug_info=debug_info)
        assert 'jazz' in debug_info['matched_keywords']
        assert debug_info['matched_keywords']['jazz'] == 1


class TestSafeFilename:
    """Tests for safe_filename in rounds.py."""

    def test_simple_name(self, app):
        """Test safe_filename with a simple string."""
        from musicround.routes.rounds import safe_filename
        result = safe_filename('My Round')
        assert result == 'My_Round'

    def test_removes_special_chars(self, app):
        """Test safe_filename removes special characters."""
        from musicround.routes.rounds import safe_filename
        result = safe_filename('Round: 2024!')
        assert '!' not in result
        assert ':' not in result

    def test_preserves_alphanumeric(self, app):
        """Test safe_filename preserves alphanumeric characters."""
        from musicround.routes.rounds import safe_filename
        result = safe_filename('Round123')
        assert 'Round123' in result

    def test_strips_whitespace(self, app):
        """Test safe_filename strips leading/trailing whitespace."""
        from musicround.routes.rounds import safe_filename
        result = safe_filename('  spaces  ')
        assert not result.startswith('_')
        assert not result.endswith('_')


class TestDeezerRoutes:
    """Tests for Deezer route endpoints."""

    def test_deezer_search_page_loads(self, app, client):
        """Test that the Deezer search page is accessible."""
        response = client.get('/deezer-search')
        assert response.status_code == 200

    def test_deezer_album_page_loads(self, app, client):
        """Test that the Deezer album import page is accessible."""
        response = client.get('/import-deezer-album')
        assert response.status_code == 200

    def test_deezer_track_page_loads(self, app, client):
        """Test that the Deezer track import page is accessible."""
        response = client.get('/import-deezer-track')
        assert response.status_code == 200

    def test_deezer_playlist_page_loads(self, app, client):
        """Test that the Deezer playlist import page is accessible."""
        response = client.get('/import-deezer-playlist')
        assert response.status_code in (200, 302)

    def test_deezer_track_import_error_hides_import_details(self, client, monkeypatch):
        """Deezer track import failures should not render raw helper errors."""
        monkeypatch.setattr(
            'musicround.routes.deezer_routes.ImportHelper.import_item',
            lambda *args, **kwargs: {
                'imported_count': 0,
                'skipped_count': 0,
                'error_count': 1,
                'errors': ['provider body token=deezer-track-secret traceback'],
            },
        )

        response = client.post(
            '/import-deezer-track-result',
            data={'track_id': 'track-err'},
            follow_redirects=True,
        )

        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert 'Error importing song from Deezer. Please check the Deezer ID and try again.' in body
        assert 'deezer-track-secret' not in body
        assert 'provider body' not in body
        assert 'traceback' not in body

    def test_deezer_playlist_import_error_hides_import_details(self, client, monkeypatch):
        """Deezer playlist import failures should not render raw helper errors."""
        monkeypatch.setattr(
            'musicround.routes.deezer_routes.ImportHelper.import_item',
            lambda *args, **kwargs: {
                'imported_count': 0,
                'skipped_count': 0,
                'error_count': 0,
                'errors': ['provider body token=deezer-playlist-secret traceback'],
            },
        )

        response = client.post(
            '/import-deezer-playlist-result',
            data={'playlist_id': 'playlist-err'},
            follow_redirects=True,
        )

        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert 'Error importing playlist from Deezer. Please check the Deezer ID and try again.' in body
        assert 'deezer-playlist-secret' not in body
        assert 'provider body' not in body
        assert 'traceback' not in body

    def test_deezer_album_import_error_hides_import_details(self, client, monkeypatch):
        """Deezer album import failures should not render raw helper errors."""
        monkeypatch.setattr(
            'musicround.routes.deezer_routes.ImportHelper.import_item',
            lambda *args, **kwargs: {
                'imported_count': 0,
                'skipped_count': 0,
                'error_count': 0,
                'errors': ['provider body token=deezer-album-secret traceback'],
            },
        )

        response = client.post(
            '/import-deezer-album-result',
            data={'album_id': 'album-err'},
            follow_redirects=True,
        )

        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert 'Error importing album from Deezer. Please check the Deezer ID and try again.' in body
        assert 'deezer-album-secret' not in body
        assert 'provider body' not in body
        assert 'traceback' not in body


class TestImportRoutesAccess:
    """Tests for basic import route access."""

    def test_official_playlists_requires_login(self, client):
        """Test that import official playlists requires authentication."""
        response = client.get('/import/official-playlists')
        assert response.status_code == 302
        assert 'login' in response.headers['Location'].lower()

    def test_direct_official_playlists_requires_login(self, client):
        """Test that direct official playlists requires authentication."""
        response = client.get('/import/direct-official-playlists')
        assert response.status_code == 302
        assert 'login' in response.headers['Location'].lower()

    def test_spotify_diagnostic_routes_require_login(self, client):
        """Direct-token and diagnostic Spotify import routes must not be anonymous."""
        for path in (
            '/import/test-spotify-client',
            '/import/raw-playlists',
            '/import/direct-auth',
        ):
            response = client.get(path)
            assert response.status_code == 302
            assert 'login' in response.headers['Location'].lower()

        response = client.post('/import/update-direct-token', data={'bearer_token': 'token'})
        assert response.status_code == 302
        assert 'login' in response.headers['Location'].lower()

    def test_spotify_diagnostic_routes_require_admin(self, app, client):
        """Spotify diagnostics expose raw provider payloads and should be admin-only."""
        _login(app, client)

        for path in ('/import/test-spotify-client', '/import/raw-playlists'):
            response = client.get(path)
            assert response.status_code == 302
            assert response.headers['Location'].endswith('/view-songs')

    def test_spotify_client_diagnostic_uses_db_token_without_session_access_token(self, app, client, monkeypatch):
        """Admins with linked Spotify tokens should not be rejected by stale session checks."""
        from musicround.routes import import_routes

        captured = {}

        class FakeOAuthSpotify:
            pass

        def fake_fetch(oauth_client, token, user_id, limit=50):
            captured['oauth_client'] = oauth_client
            captured['token'] = token
            captured['user_id'] = user_id
            return []

        _login(app, client, username='diag_admin', email='diag@example.com', is_admin=True)
        with app.app_context():
            user = User.query.filter_by(username='diag_admin').one()
            user.spotify_token = 'db-spotify-token'
            db.session.commit()

        monkeypatch.setattr(import_routes.oauth, 'spotify', FakeOAuthSpotify(), raising=False)
        monkeypatch.setattr(import_routes, 'fetch_all_user_playlists', fake_fetch)

        response = client.get('/import/test-spotify-client')

        assert response.status_code == 200
        assert b'Spotify Client Test' in response.data
        assert captured['token']['access_token'] == 'db-spotify-token'
        assert captured['user_id'] == 'spotify'

    def test_spotify_client_diagnostic_hides_exception_details(self, app, client, monkeypatch):
        """Diagnostic client errors should not render provider or token details."""
        from musicround.routes import import_routes

        _login(app, client, username='diag_error_admin', email='diagerr@example.com', is_admin=True)
        with app.app_context():
            user = User.query.filter_by(username='diag_error_admin').one()
            user.spotify_token = 'db-spotify-token'
            db.session.commit()

        monkeypatch.setattr(import_routes.oauth, 'spotify', object(), raising=False)

        def fail_fetch(oauth_client, token, user_id, limit=50):
            raise RuntimeError('provider body token=diag-client-secret traceback')

        monkeypatch.setattr(import_routes, 'fetch_all_user_playlists', fail_fetch)

        response = client.get('/import/test-spotify-client')

        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert 'Spotify diagnostic check failed. Check the server logs.' in body
        assert 'diag-client-secret' not in body
        assert 'provider body' not in body
        assert 'traceback' not in body

    def test_raw_playlists_diagnostic_hides_exception_details(self, app, client, monkeypatch):
        """Raw playlist diagnostics should not render provider or token details."""
        from musicround.routes import import_routes

        _login(app, client, username='raw_diag_admin', email='rawdiag@example.com', is_admin=True)

        class FailingSpotify:
            def get(self, *args, **kwargs):
                raise RuntimeError('provider body token=raw-playlist-secret traceback')

        monkeypatch.setattr(import_routes, 'get_spotify_token', lambda: ('db-spotify-token', 'user'))
        monkeypatch.setattr(
            'musicround.routes.import_routes.oauth.spotify',
            FailingSpotify(),
            raising=False,
        )

        response = client.get('/import/raw-playlists')

        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert 'Spotify diagnostic check failed. Check the server logs.' in body
        assert 'raw-playlist-secret' not in body
        assert 'provider body' not in body
        assert 'traceback' not in body

    def test_raw_playlists_diagnostic_bounds_query_parameters(self, app, client, monkeypatch):
        """Bad raw-playlist query params should be clamped instead of producing a 500."""
        from musicround.routes import import_routes

        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    'total': 0,
                    'items': [],
                    'next': None,
                    'previous': None,
                }

        class FakeSpotify:
            def get(self, endpoint, params=None, token=None):
                captured['endpoint'] = endpoint
                captured['params'] = params
                captured['token'] = token
                return FakeResponse()

        _login(app, client, username='raw_bounds_admin', email='rawbounds@example.com', is_admin=True)

        monkeypatch.setattr(import_routes, 'get_spotify_token', lambda: ('db-spotify-token', 'user'))
        monkeypatch.setattr(
            'musicround.routes.import_routes.oauth.spotify',
            FakeSpotify(),
            raising=False,
        )

        response = client.get('/import/raw-playlists?account=../me&limit=not-a-number&offset=-10')

        assert response.status_code == 200
        assert captured['endpoint'] == 'users/spotify/playlists'
        assert captured['params'] == {'limit': 50, 'offset': 0}
        assert captured['token']['access_token'] == 'db-spotify-token'

    def test_raw_playlists_diagnostic_clamps_large_limit(self, app, client, monkeypatch):
        """Raw playlist diagnostics should never request more than Spotify's page cap."""
        from musicround.routes import import_routes

        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    'total': 0,
                    'items': [],
                    'next': None,
                    'previous': None,
                }

        class FakeSpotify:
            def get(self, endpoint, params=None, token=None):
                captured['endpoint'] = endpoint
                captured['params'] = params
                return FakeResponse()

        _login(app, client, username='raw_limit_admin', email='rawlimit@example.com', is_admin=True)

        monkeypatch.setattr(import_routes, 'get_spotify_token', lambda: ('db-spotify-token', 'user'))
        monkeypatch.setattr(
            'musicround.routes.import_routes.oauth.spotify',
            FakeSpotify(),
            raising=False,
        )

        response = client.get('/import/raw-playlists?account=spotifycharts&limit=500&offset=3')

        assert response.status_code == 200
        assert captured['endpoint'] == 'users/spotifycharts/playlists'
        assert captured['params'] == {'limit': 50, 'offset': 3}

    def test_direct_auth_invalid_token_is_not_stored(self, app, client, monkeypatch):
        """Invalid direct bearer tokens must not remain in the session."""
        class FakeClient:
            def __init__(self, bearer_token):
                self.bearer_token = bearer_token

            def _make_api_request(self, endpoint):
                return None

        _login(app, client)
        monkeypatch.setattr('musicround.helpers.spotify_direct.SpotifyDirectClient', FakeClient)

        response = client.post('/import/direct-auth', data={'bearer_token': 'bad-token'})

        assert response.status_code == 200
        assert b'Token validation failed' in response.data
        assert b'bad-token' not in response.data
        with client.session_transaction() as sess:
            assert 'direct_bearer_token' not in sess
            assert 'direct_spotify_user' not in sess

    def test_direct_auth_success_stores_validated_token_metadata(self, app, client, monkeypatch):
        """Valid direct bearer tokens are stored with the resolved Spotify user."""
        class FakeClient:
            def __init__(self, bearer_token):
                self.bearer_token = bearer_token

            def _make_api_request(self, endpoint):
                return {'id': 'spotify-user', 'display_name': 'Spotify User'}

        _login(app, client)
        monkeypatch.setattr('musicround.helpers.spotify_direct.SpotifyDirectClient', FakeClient)

        response = client.post('/import/direct-auth', data={'bearer_token': ' valid-token '})

        assert response.status_code == 200
        assert b'Successfully authenticated as Spotify User' in response.data
        with client.session_transaction() as sess:
            assert sess['direct_bearer_token'] == 'valid-token'
            assert sess['direct_spotify_user'] == 'spotify-user'
            assert sess['direct_spotify_username'] == 'Spotify User'

    def test_update_direct_token_rejects_external_return_url(self, app, client, monkeypatch):
        """Direct-token forms must not become open redirects."""
        _login(app, client)

        response = client.post(
            '/import/update-direct-token',
            data={'clear_token': '1', 'return_url': 'https://evil.example/phish'},
        )

        assert response.status_code == 302
        assert response.headers['Location'].endswith('/import/direct-official-playlists')

    def test_update_direct_token_invalid_clears_existing_token(self, app, client, monkeypatch):
        """Replacing a direct token with an invalid value should clear the old token."""
        class FakeClient:
            def __init__(self, bearer_token):
                self.bearer_token = bearer_token

            def _make_api_request(self, endpoint):
                return None

        _login(app, client)
        with client.session_transaction() as sess:
            sess['direct_bearer_token'] = 'old-token'
            sess['direct_spotify_user'] = 'old-user'

        monkeypatch.setattr('musicround.helpers.spotify_direct.SpotifyDirectClient', FakeClient)

        response = client.post('/import/update-direct-token', data={'bearer_token': 'bad-token'})

        assert response.status_code == 302
        with client.session_transaction() as sess:
            assert 'direct_bearer_token' not in sess
            assert 'direct_spotify_user' not in sess

    def test_import_songs_page_accessible(self, app, client):
        """Test that import official playlists requires Spotify or redirects."""
        _login(app, client)
        response = client.get('/import/official-playlists')
        # Without Spotify token, it may redirect elsewhere; still a valid response
        assert response.status_code in (200, 302)

    def test_official_playlist_queue_passes_resolved_token(self, app, client, monkeypatch):
        """Official playlist imports should retain the token accepted by the route."""
        from musicround.routes import import_routes

        captured = {}

        class FakeJob:
            id = 99

        def fake_enqueue_import_job(**kwargs):
            captured.update(kwargs)
            return FakeJob()

        _login(app, client)
        monkeypatch.setattr(import_routes, 'get_spotify_token', lambda: ('manual-token', 'manual'))
        monkeypatch.setitem(app.config, 'import_queue', object())
        monkeypatch.setattr(
            'musicround.helpers.import_queue.enqueue_import_job',
            fake_enqueue_import_job,
        )

        response = client.post('/import/official-playlists', data={'playlist_id': 'playlist-123'})

        assert response.status_code == 302
        assert captured['service_name'] == 'spotify'
        assert captured['item_type'] == 'playlist'
        assert captured['item_id'] == 'playlist-123'
        assert captured['spotify_token'] == 'manual-token'

    def test_direct_official_playlist_queue_passes_direct_token(self, app, client, monkeypatch):
        """Direct official playlist imports should carry the direct bearer token into the queue."""
        captured = {}

        class FakeJob:
            id = 100

        def fake_enqueue_import_job(**kwargs):
            captured.update(kwargs)
            return FakeJob()

        _login(app, client)
        with client.session_transaction() as sess:
            sess['direct_bearer_token'] = 'direct-token'

        monkeypatch.setitem(app.config, 'import_queue', object())
        monkeypatch.setattr(
            'musicround.helpers.spotify_direct.SpotifyDirectClient',
            lambda bearer_token: object(),
        )
        monkeypatch.setattr(
            'musicround.helpers.import_queue.enqueue_import_job',
            fake_enqueue_import_job,
        )

        response = client.post('/import/direct-official-playlists', data={'playlist_id': 'playlist-456'})

        assert response.status_code == 302
        assert captured['service_name'] == 'spotify'
        assert captured['item_type'] == 'playlist'
        assert captured['item_id'] == 'playlist-456'
        assert captured['spotify_token'] == 'direct-token'

    def test_official_playlist_page_hides_stored_direct_token(self, app, client, monkeypatch):
        """Direct bearer tokens must never be rendered into OAuth-mode playlist HTML."""
        from musicround.routes import import_routes

        _login(app, client)
        with client.session_transaction() as sess:
            sess['direct_bearer_token'] = 'direct-secret-token'
            sess['direct_spotify_username'] = 'Spotify User'

        monkeypatch.setattr(import_routes, 'get_spotify_token', lambda: ('oauth-token', 'user'))
        monkeypatch.setattr(import_routes, 'fetch_all_user_playlists', lambda *args, **kwargs: [])

        response = client.get('/import/official-playlists')

        assert response.status_code == 200
        assert b'direct-secret-token' not in response.data
        assert b'Direct token saved' in response.data
        assert b'name="bearer_token" value=' not in response.data

    def test_direct_playlist_page_posts_import_forms_to_direct_endpoint(self, app, client, monkeypatch):
        """Direct-mode playlist imports must not fall back to the OAuth import route."""
        class FakeDirectClient:
            def __init__(self, bearer_token):
                self.bearer_token = bearer_token

            def fetch_all_user_playlists(self, account):
                return [{
                    'id': 'playlist-direct',
                    'name': 'Direct Playlist',
                    'description': '',
                    'images': [],
                    'owner': {'id': account},
                    'tracks': {'total': 8},
                }]

        _login(app, client)
        with client.session_transaction() as sess:
            sess['direct_bearer_token'] = 'direct-secret-token'
            sess['direct_spotify_username'] = 'Spotify User'

        monkeypatch.setattr('musicround.helpers.spotify_direct.SpotifyDirectClient', FakeDirectClient)

        response = client.get('/import/direct-official-playlists?account=spotify')

        assert response.status_code == 200
        assert b'direct-secret-token' not in response.data
        assert b'action="/import/direct-official-playlists"' in response.data
        assert b'action="/import/official-playlists"' not in response.data

    def test_update_audio_features_direct_client_init_error_hides_token(self, app, client, monkeypatch):
        """SpotifyDirectClient init errors must not expose bearer tokens in JSON."""
        _login(app, client)
        with app.app_context():
            song = Song(
                title='Needs Features',
                artist='Artist',
                genre='Rock',
                spotify_id='spotify-feature-track',
            )
            db.session.add(song)
            db.session.commit()
            song_id = song.id

        with client.session_transaction() as sess:
            sess['access_token'] = 'spotify-access-secret'

        def fail_client(*args, **kwargs):
            raise RuntimeError('provider init failed token=spotify-access-secret traceback')

        monkeypatch.setattr('musicround.helpers.spotify_direct.SpotifyDirectClient', fail_client)

        response = client.post(
            '/api/songs/update-audio-features',
            json={'song_ids': [song_id]},
        )

        body = response.get_data(as_text=True)
        data = response.get_json()
        assert response.status_code == 500
        assert data['error'] == 'SPOTIFY_DIRECT_CLIENT_INIT_FAILED'
        assert 'spotify-access-secret' not in body
        assert 'provider init failed' not in body
        assert 'traceback' not in body

    def test_queue_status_requires_login(self, client):
        """Test that queue status requires authentication."""
        response = client.get('/import/queue-status')
        assert response.status_code == 302


class TestCoreViewSongs:
    """Tests for view-songs with actual data."""

    def test_view_songs_with_songs_in_db(self, app, client):
        """Test view-songs returns songs that are in the database."""
        _login(app, client)
        with app.app_context():
            song = Song(title='Visible Song', artist='Visible Artist', genre='Rock', year=2020)
            db.session.add(song)
            db.session.commit()

        response = client.get('/view-songs')
        assert response.status_code == 200
        assert b'Visible Song' in response.data

    def test_view_songs_shows_artists(self, app, client):
        """Test view-songs shows artist names."""
        _login(app, client)
        with app.app_context():
            song = Song(title='Artist Test', artist='Known Artist XYZ', genre='Pop')
            db.session.add(song)
            db.session.commit()

        response = client.get('/view-songs')
        assert response.status_code == 200
        assert b'Known Artist XYZ' in response.data

    def test_view_songs_lazy_loads_preview_players(self, app, client):
        """The song table should not create an audio player for every preview URL."""
        _login(app, client)
        with app.app_context():
            song = Song(
                title='Preview Test',
                artist='Preview Artist',
                genre='Pop',
                preview_url='https://example.com/preview.mp3',
            )
            db.session.add(song)
            db.session.commit()

        response = client.get('/view-songs')

        assert response.status_code == 200
        assert b'preview-load-btn' in response.data
        assert b'data-preview-url="https://example.com/preview.mp3"' in response.data
        assert b'aria-label="Load preview for Preview Test by Preview Artist"' in response.data
        assert b'aria-label="Edit Preview Test by Preview Artist"' in response.data
        assert b'aria-label="Delete Preview Test by Preview Artist"' in response.data
        assert b'<audio controls class="preview-audio w-full max-w-[180px]" src=' not in response.data

    def test_view_songs_paginates_server_side(self, app, client):
        """The library page should not render the full catalog at once."""
        _login(app, client)
        with app.app_context():
            for index in range(30):
                db.session.add(
                    Song(
                        title=f'Paged Song {index:02d}',
                        artist=f'Paged Artist {index:02d}',
                        genre='Paging',
                    )
                )
            db.session.commit()

        first_page = client.get('/view-songs?per_page=25')
        second_page = client.get('/view-songs?per_page=25&page=2')

        assert first_page.status_code == 200
        assert b'Paged Song 00' in first_page.data
        assert b'Paged Song 29' not in first_page.data
        assert b'25 songs' in first_page.data

        assert second_page.status_code == 200
        assert b'Paged Song 29' in second_page.data
        assert b'Page <span id="currentPage">2</span>' in second_page.data

    def test_view_songs_filters_server_side(self, app, client):
        """Library filters should be applied by the route before rendering."""
        _login(app, client)
        with app.app_context():
            db.session.add(Song(title='Server Match', artist='Filter Artist', genre='Rock', year=1999))
            db.session.add(Song(title='Server Miss', artist='Other Artist', genre='Pop', year=2005))
            db.session.commit()

        response = client.get('/view-songs?q=Match&genre=Rock&year=1999')

        assert response.status_code == 200
        assert b'Server Match' in response.data
        assert b'Server Miss' not in response.data
        assert b'Filters are applied server-side' in response.data

    def test_view_songs_supports_analytics_action_filters(self, app, client):
        """Analytics links should land on actionable song-library filters."""
        _login(app, client)
        with app.app_context():
            db.session.add(Song(title='Missing Preview', artist='Analytics', genre='Rock', used_count=0))
            db.session.add(
                Song(
                    title='Has Preview',
                    artist='Analytics',
                    genre='Rock',
                    used_count=3,
                    preview_url='https://example.com/has-preview.mp3',
                )
            )
            db.session.add(Song(title='Unknown Genre', artist='Analytics', genre='Unknown', used_count=0))
            db.session.add(Song(title='Spaced Unknown Genre', artist='Analytics', genre=' Unknown ', used_count=0))
            db.session.add(Song(title='Blank Genre', artist='Analytics', genre='   ', used_count=0))
            db.session.add(Song(title='Spaced Rock', artist='Analytics', genre=' Rock ', used_count=0))
            db.session.add(Song(title='Spaced Hip Hop', artist='Analytics', genre=' Hip   Hop ', used_count=0))
            db.session.commit()

        missing_preview = client.get('/view-songs?has_preview=false')
        unused = client.get('/view-songs?used_max=0')
        missing_genre = client.get('/view-songs?genre=__missing__')
        rock_genre = client.get('/view-songs?genre=Rock')
        hip_hop_genre = client.get('/view-songs?genre=Hip+++Hop')

        assert b'Missing Preview' in missing_preview.data
        assert b'Has Preview' not in missing_preview.data
        assert b'Missing Preview' in unused.data
        assert b'Has Preview' not in unused.data
        assert b'Unknown Genre' in missing_genre.data
        assert b'Spaced Unknown Genre' in missing_genre.data
        assert b'Blank Genre' in missing_genre.data
        assert b'Has Preview' not in missing_genre.data
        assert b'Spaced Rock' in rock_genre.data
        assert b'Unknown Genre' not in rock_genre.data
        assert b'Spaced Hip Hop' in hip_hop_genre.data
        assert b'Spaced Rock' not in hip_hop_genre.data
