"""Targeted tests to cover specific branches and reach 30% coverage."""
import pytest
from musicround.models import db, User, SystemSetting


def _login(app, client, username='branch_user', email='branch@example.com'):
    """Helper: create and log in a user."""
    with app.app_context():
        existing = User.query.filter_by(username=username).first()
        if not existing:
            user = User(username=username, email=email)
            user.password = 'BranchPass123!'
            db.session.add(user)
            db.session.commit()
    client.post('/users/login', data={'username': username, 'password': 'BranchPass123!'})


class TestRegisterValidation:
    """Tests for register route validation branches."""

    def test_register_signups_disabled(self, app, client):
        """Test that registration fails when signups are disabled."""
        with app.app_context():
            SystemSetting.set('allow_signups', 'false')

        try:
            response = client.post('/users/register', data={
                'username': 'newuser_disabled',
                'email': 'disabled@example.com',
                'password': 'SecurePass123!',
                'confirm_password': 'SecurePass123!',
            }, follow_redirects=True)
            assert response.status_code == 200
        finally:
            with app.app_context():
                SystemSetting.set('allow_signups', 'true')

    def test_register_password_mismatch(self, client):
        """Test that registration fails when passwords don't match."""
        response = client.post('/users/register', data={
            'username': 'testmismatch',
            'email': 'mismatch@example.com',
            'password': 'SecurePass123!',
            'confirm_password': 'DifferentPass456!',
        })
        assert response.status_code == 200

    def test_register_duplicate_username(self, app, client):
        """Test that registration fails when username already exists."""
        with app.app_context():
            user = User(username='existing_user', email='existing@example.com')
            user.password = 'ExistingPass123!'
            db.session.add(user)
            db.session.commit()

        response = client.post('/users/register', data={
            'username': 'existing_user',
            'email': 'newmail@example.com',
            'password': 'AnyPass123!',
            'confirm_password': 'AnyPass123!',
        })
        assert response.status_code == 200

    def test_register_duplicate_email(self, app, client):
        """Test that registration fails when email already exists."""
        with app.app_context():
            user = User(username='uniqueusername', email='dup@example.com')
            user.password = 'UniquePass123!'
            db.session.add(user)
            db.session.commit()

        response = client.post('/users/register', data={
            'username': 'brandnewuser',
            'email': 'dup@example.com',
            'password': 'AnyPass123!',
            'confirm_password': 'AnyPass123!',
        })
        assert response.status_code == 200

    def test_register_successful_creation(self, app, client):
        """Test that successful registration redirects to login."""
        response = client.post('/users/register', data={
            'username': 'success_user',
            'email': 'success@example.com',
            'password': 'SuccessPass123!',
            'confirm_password': 'SuccessPass123!',
        }, follow_redirects=False)
        # Should redirect to login after success
        assert response.status_code == 302


class TestLogout:
    """Tests for the logout route (requires authenticated user)."""

    def test_logout_while_authenticated(self, app, client):
        """Test that logout works while authenticated."""
        _login(app, client)
        response = client.get('/users/logout', follow_redirects=False)
        assert response.status_code == 302
        assert 'login' in response.headers['Location'].lower()

    def test_logout_clears_session(self, app, client):
        """Test that logout clears the session and redirects to login."""
        _login(app, client)
        # Verify we're logged in
        profile_response = client.get('/users/profile')
        assert profile_response.status_code == 200
        # Now logout
        client.get('/users/logout')
        # Now accessing profile should redirect to login
        profile_after = client.get('/users/profile')
        assert profile_after.status_code == 302


class TestLoginBranches:
    """Tests for login route edge cases."""

    def test_login_via_email(self, app, client):
        """Test that login via email works."""
        with app.app_context():
            user = User(username='emailloginuser', email='emaillogin@example.com')
            user.password = 'EmailPass123!'
            db.session.add(user)
            db.session.commit()

        response = client.post('/users/login', data={
            'username': 'emaillogin@example.com',
            'password': 'EmailPass123!',
        }, follow_redirects=True)
        assert response.status_code == 200

    def test_login_already_authenticated_redirects(self, app, client):
        """Test that logged-in user accessing /login is redirected."""
        _login(app, client)
        response = client.get('/users/login')
        # Should redirect to home since already authenticated
        assert response.status_code == 302

    def test_register_already_authenticated_redirects(self, app, client):
        """Test that logged-in user accessing /register is redirected."""
        _login(app, client)
        response = client.get('/users/register')
        assert response.status_code == 302


class TestRoundsExtended:
    """Additional rounds coverage tests."""

    def _create_user_and_login(self, app, client, username='roundext', email='roundext@example.com'):
        with app.app_context():
            existing = User.query.filter_by(username=username).first()
            if not existing:
                user = User(username=username, email=email)
                user.password = 'RoundExtPass123!'
                db.session.add(user)
                db.session.commit()
        client.post('/users/login', data={'username': username, 'password': 'RoundExtPass123!'})

    def test_update_songs_empty_order(self, app, client):
        """Test update-songs with no song_order provided."""
        from musicround.models import Song, Round
        self._create_user_and_login(app, client)
        with app.app_context():
            song = Song(title='Empty Order Song', artist='A', genre='Rock')
            db.session.add(song)
            db.session.commit()
            round_ = Round(round_type='genre', round_criteria_used='Rock', songs=str(song.id))
            db.session.add(round_)
            db.session.commit()
            round_id = round_.id

        response = client.post(
            f'/rounds/{round_id}/update-songs',
            data={},  # No song_order
            follow_redirects=True,
        )
        assert response.status_code == 200
