"""Tests for Flask routes."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from authlib.integrations.base_client.errors import OAuthError

from musicround.models import db, User, Song, Round, Tag


class TestCoreRoutes:
    """Tests for core blueprint routes."""

    def test_index_unauthenticated_redirects_to_login(self, client):
        """Test that unauthenticated access to / redirects to login."""
        response = client.get('/')
        assert response.status_code == 302
        assert 'login' in response.headers['Location'].lower()

    def test_view_songs_requires_login(self, client):
        """Test that /view-songs requires authentication."""
        response = client.get('/view-songs')
        assert response.status_code == 302
        assert 'login' in response.headers['Location'].lower()

    def test_search_requires_login(self, client):
        """Test that /search requires authentication."""
        response = client.get('/search')
        assert response.status_code == 302
        assert 'login' in response.headers['Location'].lower()


class TestUserRoutes:
    """Tests for user-related routes."""

    def test_login_page_accessible(self, client):
        """Test that the login page is accessible without authentication."""
        response = client.get('/users/login')
        assert response.status_code == 200

    def test_register_page_accessible(self, client):
        """Test that the register page is accessible without authentication."""
        response = client.get('/users/register')
        assert response.status_code == 200

    def test_logout_redirects(self, client):
        """Test that /logout redirects (even for unauthenticated users)."""
        response = client.get('/users/logout')
        # Should redirect somewhere (login page)
        assert response.status_code in (302, 200)

    def test_profile_requires_login(self, client):
        """Test that /users/profile requires authentication."""
        response = client.get('/users/profile')
        assert response.status_code == 302
        assert 'login' in response.headers['Location'].lower()

    def test_register_post_missing_fields(self, client):
        """Test that register POST with missing required fields stays on page."""
        response = client.post('/users/register', data={}, follow_redirects=True)
        assert response.status_code == 200

    def test_register_post_valid_data(self, app, client):
        """Test that registering a user with valid data succeeds."""
        response = client.post('/users/register', data={
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password': 'SecurePass123!',
            'confirm_password': 'SecurePass123!',
        }, follow_redirects=True)
        assert response.status_code == 200
        # User should now exist in db
        with app.app_context():
            user = User.query.filter_by(username='newuser').first()
            assert user is not None

    def test_login_post_invalid_credentials(self, client):
        """Test that login with invalid credentials fails gracefully."""
        response = client.post('/users/login', data={
            'username': 'nobody',
            'password': 'wrongpass',
        }, follow_redirects=True)
        assert response.status_code == 200

    def test_login_post_valid_credentials(self, app, client):
        """Test that login with valid credentials works."""
        # First create a user
        with app.app_context():
            user = User(username='logintest', email='logintest@example.com')
            user.password = 'ValidPass123!'
            db.session.add(user)
            db.session.commit()

        response = client.post('/users/login', data={
            'username': 'logintest',
            'password': 'ValidPass123!',
        }, follow_redirects=True)
        assert response.status_code == 200


class TestSpotifyLoginCallbackSecurity:
    """Tests for Spotify OAuth login callback error handling."""

    def test_callback_failure_hides_oauth_exception_details(self, client):
        """OAuth callback failures must not render provider or token details."""
        mock_spotify_client = MagicMock()
        mock_spotify_client.authorize_access_token.side_effect = Exception(
            'invalid_grant access_token=sp-secret refresh_token=sp-refresh'
        )

        with patch('musicround.routes.auth.oauth.spotify', new=mock_spotify_client, create=True):
            response = client.get('/callback', follow_redirects=True)

        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert 'Spotify login failed. Please try again or reconnect Spotify.' in body
        assert 'invalid_grant' not in body
        assert 'sp-secret' not in body
        assert 'sp-refresh' not in body


class TestApiRoutes:
    """Tests for API blueprint routes."""

    def test_list_tags_no_auth_required(self, client):
        """Test /api/tags is publicly accessible and returns a tags dict."""
        response = client.get('/api/tags')
        assert response.status_code == 200
        data = response.get_json()
        assert 'tags' in data
        assert isinstance(data['tags'], list)

    def test_song_detail_unauthenticated_returns_404_or_redirect(self, client):
        """Test /api/songs/<id> returns 404 for nonexistent song (no auth required)."""
        response = client.get('/api/songs/99999')
        # Song doesn't exist, so should 404; endpoint itself is not auth-gated
        assert response.status_code in (302, 401, 403, 404)

    def test_search_songs_unauthenticated_redirects(self, client):
        """Test /api/songs/search requires authentication."""
        response = client.get('/api/songs/search?q=test')
        assert response.status_code in (302, 401, 403)

    def test_spotify_album_requires_login(self, client):
        """These endpoints previously always 401'd (they checked a session key
        that was never set anywhere), so being unauthenticated was never
        actually a security boundary. Now that a token can be resolved (and
        could fall back to the shared system account), they must require
        login so anonymous callers can't use the service account's token."""
        response = client.get('/api/spotify/album/abc123')
        assert response.status_code == 302
        assert 'login' in response.headers['Location'].lower()

    def test_spotify_album_uses_manual_session_bearer_token(self, app, client):
        """A manually-supplied bearer token (users.update_bearer_token) must be
        usable for these endpoints instead of always failing."""
        with app.app_context():
            user = User(username='apitokenuser', email='apitokenuser@example.com')
            user.password = 'TestPass123!'
            db.session.add(user)
            db.session.commit()
        client.post('/users/login', data={'username': 'apitokenuser', 'password': 'TestPass123!'})

        with client.session_transaction() as sess:
            sess['access_token'] = 'manually-extracted-token'
            sess['bearer_token_added'] = datetime.now().timestamp()

        fake_album = {
            'id': 'abc123', 'name': 'Test Album', 'artists': [{'name': 'Test Artist'}],
            'release_date': '2020-01-01', 'images': [], 'total_tracks': 1,
        }
        fake_tracks = {'items': [{'name': 'Track 1', 'artists': [{'name': 'Test Artist'}],
                                  'duration_ms': 1000, 'track_number': 1}]}

        def fake_get(url, headers=None, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = fake_tracks if 'tracks' in url else fake_album
            return resp

        with patch('musicround.routes.api.requests.get', side_effect=fake_get) as mock_get:
            response = client.get('/api/spotify/album/abc123')

        assert response.status_code == 200
        # The manually-supplied token must be the one used for the request.
        assert mock_get.call_args_list[0].kwargs['headers']['Authorization'] == 'Bearer manually-extracted-token'


class TestRoundsRoutes:
    """Tests for rounds blueprint routes."""

    def test_rounds_index_requires_login(self, client):
        """Test that rounds index page requires authentication."""
        response = client.get('/rounds/')
        assert response.status_code in (302, 404)

    def test_view_round_requires_login(self, client):
        """Test that viewing a round requires authentication."""
        response = client.get('/rounds/view/1')
        assert response.status_code in (302, 404)


class TestErrorHandling:
    """Tests for error handling."""

    def test_404_returns_error_page(self, client):
        """Test that a non-existent route returns a 404."""
        response = client.get('/this-page-does-not-exist-at-all-xyz')
        assert response.status_code == 404

    def test_app_is_in_testing_mode(self, app):
        """Test that the test app is correctly in testing mode."""
        assert app.config['TESTING'] is True
        assert app.config['WTF_CSRF_ENABLED'] is False


class TestAuthenticatedRoutes:
    """Tests for routes that require authentication, tested while logged in."""

    def _login(self, app, client):
        """Helper: create a user and log in."""
        with app.app_context():
            user = User(username='authtest', email='authtest@example.com')
            user.password = 'TestPass123!'
            db.session.add(user)
            db.session.commit()
        client.post('/users/login', data={
            'username': 'authtest',
            'password': 'TestPass123!',
        })

    def test_view_songs_accessible_when_logged_in(self, app, client):
        """Test that view-songs is accessible when logged in."""
        self._login(app, client)
        response = client.get('/view-songs')
        assert response.status_code == 200

    def test_search_accessible_when_logged_in(self, app, client):
        """Test that search page is accessible when logged in."""
        self._login(app, client)
        response = client.get('/search')
        assert response.status_code == 200

    def test_index_accessible_when_logged_in(self, app, client):
        """Test that homepage is accessible when logged in."""
        self._login(app, client)
        response = client.get('/')
        assert response.status_code == 200

    def test_profile_accessible_when_logged_in(self, app, client):
        """Test that profile page is accessible when logged in."""
        self._login(app, client)
        response = client.get('/users/profile')
        assert response.status_code == 200

    def test_profile_does_not_render_manual_spotify_token(self, app, client):
        """Stored manual bearer tokens must stay hidden in profile HTML."""
        self._login(app, client)
        with client.session_transaction() as sess:
            sess['access_token'] = 'manual-spotify-secret-token'
            sess['bearer_token_added'] = datetime.now().timestamp()
            sess['token_source'] = 'manual'

        response = client.get('/users/profile')

        assert response.status_code == 200
        assert b'manual-spotify-secret-token' not in response.data
        assert b'Manual token saved' in response.data

    def test_profile_discards_expired_manual_spotify_token_before_validation(self, app, client, monkeypatch):
        """Expired manual tokens should be removed before the profile tries to reuse them."""
        from musicround.routes import users as users_routes

        self._login(app, client)
        fake_spotify = MagicMock()
        monkeypatch.setattr(users_routes.oauth, 'spotify', fake_spotify, raising=False)
        with client.session_transaction() as sess:
            sess['access_token'] = 'expired-manual-token'
            sess['bearer_token_added'] = (datetime.now() - timedelta(hours=2)).timestamp()
            sess['token_source'] = 'manual'
            sess['client_token_expiry'] = (datetime.now() + timedelta(hours=1)).timestamp()

        response = client.get('/users/profile')

        assert response.status_code == 200
        fake_spotify.get.assert_not_called()
        assert b'expired-manual-token' not in response.data
        with client.session_transaction() as sess:
            assert 'access_token' not in sess
            assert 'bearer_token_added' not in sess
            assert 'token_source' not in sess
            assert 'client_token_expiry' not in sess

    def test_profile_clears_rejected_manual_spotify_token(self, app, client, monkeypatch):
        """A manual token rejected by Spotify must not stay active on the profile."""
        from musicround.routes import users as users_routes

        self._login(app, client)

        class FakeResponse:
            ok = False
            status_code = 401
            text = 'invalid token'

            def json(self):
                return {}

        fake_spotify = MagicMock()
        fake_spotify.get.return_value = FakeResponse()
        monkeypatch.setattr(users_routes.oauth, 'spotify', fake_spotify, raising=False)
        with client.session_transaction() as sess:
            sess['access_token'] = 'rejected-manual-token'
            sess['bearer_token_added'] = datetime.now().timestamp()
            sess['token_source'] = 'manual'

        response = client.get('/users/profile')

        assert response.status_code == 200
        assert b'rejected-manual-token' not in response.data
        assert b'Manually entered Spotify token is invalid or expired.' in response.data
        with client.session_transaction() as sess:
            assert 'access_token' not in sess
            assert 'bearer_token_added' not in sess
            assert 'token_source' not in sess

    def test_update_bearer_token_invalid_token_is_not_stored(self, app, client, monkeypatch):
        """Invalid manual Spotify tokens must not poison later Spotify calls."""
        from musicround.routes import users as users_routes

        self._login(app, client)
        with client.session_transaction() as sess:
            sess['access_token'] = 'old-manual-token'
            sess['bearer_token_added'] = datetime.now().timestamp()
            sess['token_source'] = 'manual'
            sess['client_token_expiry'] = (datetime.now() + timedelta(hours=1)).timestamp()

        class FakeResponse:
            ok = False
            status_code = 401

            def json(self):
                return {}

        fake_spotify = MagicMock()
        fake_spotify.get.return_value = FakeResponse()
        monkeypatch.setattr(users_routes.oauth, 'spotify', fake_spotify, raising=False)

        response = client.post(
            '/users/update-bearer-token',
            data={'bearer_token': 'bad-token'},
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert b'bad-token' not in response.data
        assert b'Token validation failed. The token was not saved.' in response.data
        with client.session_transaction() as sess:
            assert 'access_token' not in sess
            assert 'bearer_token_added' not in sess
            assert 'token_source' not in sess
            assert 'client_token_expiry' not in sess

    def test_update_bearer_token_valid_user_token_is_stored(self, app, client, monkeypatch):
        """A validated user OAuth token may be stored as a manual session token."""
        from musicround.routes import users as users_routes

        self._login(app, client)

        class FakeResponse:
            ok = True

            def json(self):
                return {'id': 'spotify-user-id', 'display_name': 'Manual User'}

        fake_spotify = MagicMock()
        fake_spotify.get.return_value = FakeResponse()
        monkeypatch.setattr(users_routes.oauth, 'spotify', fake_spotify, raising=False)

        response = client.post(
            '/users/update-bearer-token',
            data={'bearer_token': ' valid-user-token '},
            follow_redirects=True,
        )

        assert response.status_code == 200
        with client.session_transaction() as sess:
            assert sess['access_token'] == 'valid-user-token'
            assert sess['token_source'] == 'user_manual'
            assert 'bearer_token_added' in sess
            assert 'client_token_expiry' not in sess

    def test_update_bearer_token_valid_client_token_is_stored(self, app, client, monkeypatch):
        """A validated client-credentials token remains supported for shared searches."""
        from musicround.routes import users as users_routes

        self._login(app, client)

        class FakeUserResponse:
            ok = True
            status_code = 200

            def json(self):
                return {}

        class FakeBrowseResponse:
            ok = True

            def json(self):
                return {'albums': {'items': []}}

        fake_spotify = MagicMock()
        fake_spotify.get.side_effect = [FakeUserResponse(), FakeBrowseResponse()]
        monkeypatch.setattr(users_routes.oauth, 'spotify', fake_spotify, raising=False)

        response = client.post(
            '/users/update-bearer-token',
            data={'bearer_token': 'client-token'},
            follow_redirects=True,
        )

        assert response.status_code == 200
        with client.session_transaction() as sess:
            assert sess['access_token'] == 'client-token'
            assert sess['token_source'] == 'client_credentials_manual'
            assert 'bearer_token_added' in sess
            assert 'client_token_expiry' in sess

    def test_profile_debug_panels_do_not_render_token_fragments(self, app, client):
        """Admin profile diagnostics should show token presence without token previews."""
        from musicround.models import SystemSetting

        self._login(app, client)
        with app.app_context():
            user = User.query.filter_by(username='authtest').one()
            user.is_admin = True
            user.spotify_id = 'spotify-account-id'
            user.spotify_token = 'spotify-access-secret-token'
            user.spotify_refresh_token = 'spotify-refresh-secret-token'
            user.dropbox_id = 'dropbox-account-id'
            user.dropbox_token = 'dropbox-access-secret-token'
            user.dropbox_refresh_token = 'dropbox-refresh-secret-token'
            SystemSetting.set('fallback_spotify_refresh_token', 'system-refresh-secret-token')
            db.session.commit()

        with client.session_transaction() as sess:
            sess['access_token'] = 'manual-profile-secret-token'
            sess['bearer_token_added'] = datetime.now().timestamp()
            sess['token_source'] = 'manual'

        response = client.get('/users/profile')

        body = response.data
        assert response.status_code == 200
        for secret in (
            b'spotify-access-secret-token',
            b'spotify-refresh-secret-token',
            b'dropbox-access-secret-token',
            b'dropbox-refresh-secret-token',
            b'system-refresh-secret-token',
            b'manual-profile-secret-token',
        ):
            assert secret not in body
        assert b'Hidden for security' in body
        assert b'Stored and hidden for security' in body

    def test_profile_shows_dropbox_reconnect_when_credentials_cleared(self, app, client):
        """A preserved Dropbox id without tokens should become actionable."""
        self._login(app, client)
        with app.app_context():
            user = User.query.filter_by(username='authtest').one()
            user.dropbox_id = 'dropbox-account-id'
            user.dropbox_token = None
            user.dropbox_refresh_token = None
            user.dropbox_token_expiry = None
            db.session.commit()

        response = client.get('/users/profile')

        assert response.status_code == 200
        assert b'Reconnect required' in response.data
        assert b'Reconnect Dropbox' in response.data

    def test_profile_shows_spotify_reconnect_when_credentials_cleared(self, app, client):
        """A preserved Spotify id without tokens should become actionable."""
        self._login(app, client)
        with app.app_context():
            user = User.query.filter_by(username='authtest').one()
            user.is_admin = True
            user.spotify_id = 'spotify-account-id'
            user.spotify_token = None
            user.spotify_refresh_token = None
            user.spotify_token_expiry = None
            db.session.commit()

        response = client.get('/users/profile')

        assert response.status_code == 200
        assert b'Reconnect required' in response.data
        assert b'Reconnect Spotify' in response.data

    def test_profile_warns_when_spotify_token_expires_soon(self, app, client):
        """Profile should surface a clear warning for short-lived Spotify tokens."""
        self._login(app, client)
        with app.app_context():
            user = User.query.filter_by(username='authtest').one()
            user.is_admin = True
            user.spotify_id = 'spotify-account-id'
            user.spotify_token = 'access-token'
            user.spotify_refresh_token = 'refresh-token'
            user.spotify_token_expiry = datetime.now() + timedelta(minutes=5)
            db.session.commit()

        response = client.get('/users/profile')

        assert response.status_code == 200
        assert b'Token expires soon' in response.data
        assert b'long import' in response.data

    def test_profile_warns_when_dropbox_token_expires_soon(self, app, client):
        """Profile should surface a clear warning before Dropbox exports become fragile."""
        self._login(app, client)
        with app.app_context():
            user = User.query.filter_by(username='authtest').one()
            user.dropbox_id = 'dropbox-account-id'
            user.dropbox_token = 'access-token'
            user.dropbox_refresh_token = 'refresh-token'
            user.dropbox_token_expiry = datetime.now() + timedelta(minutes=5)
            db.session.commit()

        response = client.get('/users/profile')

        assert response.status_code == 200
        assert b'Token expires soon' in response.data
        assert b'before exporting a round package' in response.data

    def test_legacy_use_refresh_token_redirects_when_logged_in(self, app, client):
        """Legacy refresh-token endpoint must not return None/500."""
        self._login(app, client)
        response = client.post('/users/use-refresh-token')
        assert response.status_code == 302
        assert response.headers['Location'].endswith('/users/profile')

    def test_spotify_link_page_normalizes_oauth_profile_name(self, app, client):
        """Spotify link page should display OAuth profile names even without display_name."""
        self._login(app, client)
        with app.app_context():
            user = User.query.filter_by(username='authtest').one()
            user.spotify_id = 'spotify-account-id'
            user.spotify_token = 'access-token'
            user.spotify_refresh_token = 'refresh-token'
            user.spotify_token_expiry = datetime.now() + timedelta(hours=1)
            db.session.commit()

        with client.session_transaction() as sess:
            sess['spotify_user_info'] = {
                'id': 'spotify-account-id',
                'name': 'Christian Spotify',
            }

        response = client.get('/users/spotify-link')

        assert response.status_code == 200
        assert b'Display Name: Christian Spotify' in response.data

    def test_api_tags_accessible_when_logged_in(self, app, client):
        """Test that API tags endpoint is accessible when logged in."""
        self._login(app, client)
        response = client.get('/api/tags')
        assert response.status_code == 200
        data = response.get_json()
        assert 'tags' in data
        assert isinstance(data['tags'], list)

    def test_api_search_songs_when_logged_in(self, app, client):
        """Test that song search API is accessible when logged in."""
        self._login(app, client)
        response = client.get('/api/songs/search?q=test')
        assert response.status_code == 200


class TestSpotifySearchInvalidGrant:
    """Spotify refresh tokens expire after six months starting 2026-07-20.

    When Authlib's automatic refresh hits invalid_grant during a search, the
    stored tokens must be discarded and the user sent to reconnect, instead
    of the error surfacing as a generic failure.
    """

    def _login_with_spotify(self, app, client):
        with app.app_context():
            user = User(username='spotifyuser', email='spotifyuser@example.com')
            user.password = 'TestPass123!'
            user.spotify_id = 'spotify-user-1'
            user.spotify_token = 'old-access-token'
            user.spotify_refresh_token = 'old-refresh-token'
            user.spotify_token_expiry = datetime.now() + timedelta(hours=1)
            db.session.add(user)
            db.session.commit()
            user_id = user.id
        client.post('/users/login', data={
            'username': 'spotifyuser',
            'password': 'TestPass123!',
        })
        return user_id

    def test_invalid_grant_clears_tokens_and_redirects_to_reconnect(self, app, client):
        user_id = self._login_with_spotify(app, client)

        # The Spotify OAuth client is only registered when SPOTIFY_CLIENT_ID/SECRET
        # are configured, so `oauth.spotify` doesn't exist in the test app; patch
        # it in directly to simulate Authlib raising invalid_grant during refresh.
        mock_spotify_client = MagicMock()
        mock_spotify_client.get.side_effect = OAuthError(error='invalid_grant')
        with patch('musicround.routes.core.oauth.spotify', new=mock_spotify_client, create=True):
            response = client.post(
                '/search-results',
                data={'search_term': 'some song'},
                follow_redirects=False,
            )

        assert response.status_code == 302
        assert 'spotify' in response.headers['Location'].lower()

        with app.app_context():
            user = db.session.get(User, user_id)
            assert user.spotify_token is None
            assert user.spotify_refresh_token is None
            assert user.spotify_token_expiry is None
            # The linked-account identity must survive; the user only needs
            # to reconnect, not re-link their Spotify account from scratch.
            assert user.spotify_id == 'spotify-user-1'

    def test_401_during_search_clears_tokens_but_keeps_spotify_id(self, app, client):
        """A plain 401 (not an OAuthError) on the user's own token must clear
        the token/refresh_token/expiry but must not unlink the account."""
        user_id = self._login_with_spotify(app, client)

        import requests
        fake_401_response = MagicMock()
        fake_401_response.status_code = 401
        fake_401_response.text = 'invalid token'
        http_error = requests.exceptions.HTTPError(response=fake_401_response)

        mock_spotify_client = MagicMock()
        mock_spotify_client.get.side_effect = http_error
        mock_spotify_client.token = None
        with patch('musicround.routes.core.oauth.spotify', new=mock_spotify_client, create=True):
            response = client.post(
                '/search-results',
                data={'search_term': 'some song'},
                follow_redirects=False,
            )

        assert response.status_code == 302

        with app.app_context():
            user = db.session.get(User, user_id)
            assert user.spotify_token is None
            assert user.spotify_refresh_token is None
            assert user.spotify_token_expiry is None
            assert user.spotify_id == 'spotify-user-1'

    def test_generic_search_error_hides_exception_details(self, app, client):
        """Generic Spotify search errors must not render raw exception details."""
        self._login_with_spotify(app, client)

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            'tracks': {'items': []}, 'albums': {'items': []}, 'playlists': {'items': []}
        }
        mock_spotify_client = MagicMock()
        mock_spotify_client.get.return_value = fake_response
        mock_spotify_client.token = None
        from flask import render_template as real_render_template

        def flaky_render_template(template_name, **context):
            if template_name == 'service_search_results.html':
                raise RuntimeError('provider body search-secret traceback')
            return real_render_template(template_name, **context)

        with patch('musicround.routes.core.oauth.spotify', new=mock_spotify_client, create=True), \
                patch('musicround.routes.core.render_template', side_effect=flaky_render_template):
            response = client.post(
                '/search-results',
                data={'search_term': 'some song'},
                follow_redirects=False,
            )

        body = response.get_data(as_text=True)
        assert response.status_code == 500
        assert 'Error 500' in body
        assert 'An error occurred while searching Spotify.' in body
        assert 'Please try again or reconnect Spotify if the problem persists.' in body
        assert 'search-secret' not in body
        assert 'provider body' not in body
        assert 'traceback' not in body


class TestSpotifySearchManualTokenPriority:
    """A manually-supplied session bearer token (e.g. extracted from a
    Spotify web session, see users.update_bearer_token) must be used instead
    of the user's own linked Spotify account, and a failure with it must not
    touch that account's stored tokens.
    """

    def _login_with_spotify(self, app, client):
        with app.app_context():
            user = User(username='manualtokenuser', email='manualtokenuser@example.com')
            user.password = 'TestPass123!'
            user.spotify_id = 'spotify-user-1'
            user.spotify_token = 'db-access-token'
            user.spotify_refresh_token = 'db-refresh-token'
            user.spotify_token_expiry = datetime.now() + timedelta(hours=1)
            db.session.add(user)
            db.session.commit()
            user_id = user.id
        client.post('/users/login', data={
            'username': 'manualtokenuser',
            'password': 'TestPass123!',
        })
        return user_id

    def test_manual_session_token_used_instead_of_users_db_token(self, app, client):
        self._login_with_spotify(app, client)
        with client.session_transaction() as sess:
            sess['access_token'] = 'manually-extracted-token'
            sess['bearer_token_added'] = datetime.now().timestamp()

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            'tracks': {'items': []}, 'albums': {'items': []}, 'playlists': {'items': []}
        }

        mock_spotify_client = MagicMock()
        mock_spotify_client.get.return_value = fake_response
        mock_spotify_client.token = None
        with patch('musicround.routes.core.oauth.spotify', new=mock_spotify_client, create=True):
            client.post('/search-results', data={'search_term': 'some song'})

        # The manual token, not the user's own DB token, must have been used,
        # and with no refresh_token so Authlib won't try to auto-refresh it.
        used_token = mock_spotify_client.get.call_args_list[0].kwargs['token']
        assert used_token['access_token'] == 'manually-extracted-token'
        assert used_token['refresh_token'] is None

    def test_manual_token_401_does_not_clear_users_db_tokens(self, app, client):
        user_id = self._login_with_spotify(app, client)
        with client.session_transaction() as sess:
            sess['access_token'] = 'manually-extracted-token'
            sess['bearer_token_added'] = datetime.now().timestamp()

        import requests
        fake_401_response = MagicMock()
        fake_401_response.status_code = 401
        fake_401_response.text = 'invalid token'
        http_error = requests.exceptions.HTTPError(response=fake_401_response)

        mock_spotify_client = MagicMock()
        mock_spotify_client.get.side_effect = http_error
        mock_spotify_client.token = None
        with patch('musicround.routes.core.oauth.spotify', new=mock_spotify_client, create=True):
            client.post('/search-results', data={'search_term': 'some song'}, follow_redirects=False)

        with app.app_context():
            user = db.session.get(User, user_id)
            # Only the manually-supplied token was bad - the user's own linked
            # Spotify account must be left untouched.
            assert user.spotify_token == 'db-access-token'
            assert user.spotify_refresh_token == 'db-refresh-token'
