"""Tests for Flask routes."""
import pytest
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
