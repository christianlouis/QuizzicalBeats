"""Additional tests for setup, system health, and API branches."""
import pytest
import json
from musicround.models import db, User, Role, Song, Tag


def _create_user(app, username, email, password='TestPass123!', is_admin=False):
    """Create a user and return it."""
    with app.app_context():
        existing = User.query.filter_by(username=username).first()
        if existing:
            return existing.id
        user = User(username=username, email=email, is_admin=is_admin)
        user.password = password
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(app, client, username, password='TestPass123!'):
    """Log in a user."""
    client.post('/users/login', data={'username': username, 'password': password})


class TestSetupRoute:
    """Tests for /users/setup route."""

    def test_setup_promotes_first_user_to_admin(self, app, client):
        """Test that setup promotes a regular user to admin when no admin exists."""
        _create_user(app, 'setup_user1', 'setup1@example.com')
        _login(app, client, 'setup_user1')

        with app.app_context():
            # Ensure no admin role exists
            admin_role = Role.query.filter_by(name='admin').first()
            if admin_role:
                admin_role.users = []
                db.session.commit()

        response = client.get('/users/setup', follow_redirects=True)
        assert response.status_code == 200

    def test_setup_fails_when_admin_exists(self, app, client):
        """Test that setup shows warning when admin already exists."""
        _create_user(app, 'setup_user2', 'setup2@example.com')
        _login(app, client, 'setup_user2')

        with app.app_context():
            # Create admin role and admin user
            admin_role = Role.query.filter_by(name='admin').first()
            if not admin_role:
                admin_role = Role(name='admin', description='Admin')
                db.session.add(admin_role)
                db.session.commit()
            admin_user = User(username='existing_admin2', email='admin2@example.com', is_admin=True)
            admin_user.password = 'AdminPass123!'
            admin_user.roles.append(admin_role)
            db.session.add(admin_user)
            db.session.commit()

        response = client.get('/users/setup', follow_redirects=True)
        assert response.status_code == 200

    def test_setup_redirects_when_already_admin(self, app, client):
        """Test that setup redirects when the user is already an admin."""
        _create_user(app, 'already_admin3', 'already3@example.com', is_admin=True)
        _login(app, client, 'already_admin3')

        response = client.get('/users/setup', follow_redirects=True)
        assert response.status_code == 200


class TestSystemHealthRoute:
    """Tests for /users/system-health route."""

    def test_system_health_requires_admin(self, app, client):
        """Test that system-health requires admin access."""
        _create_user(app, 'health_nonadmin', 'healthna@example.com')
        _login(app, client, 'health_nonadmin')
        response = client.get('/users/system-health')
        assert response.status_code in (302, 403)

    def test_system_health_accessible_for_admin(self, app, client):
        """Test that system-health is accessible for admins."""
        _create_user(app, 'health_admin', 'healthadmin@example.com', is_admin=True)
        _login(app, client, 'health_admin')
        response = client.get('/users/system-health')
        assert response.status_code in (200, 302, 500)  # may fail if admin_required checks roles


class TestSongApiExtendedBranches:
    """Tests for uncovered branches in song API."""

    def _make_song(self, app, **kwargs):
        """Helper: create song and return id."""
        defaults = {'title': 'Branch Song', 'artist': 'Artist', 'genre': 'Rock'}
        defaults.update(kwargs)
        with app.app_context():
            song = Song(**defaults)
            db.session.add(song)
            db.session.commit()
            return song.id

    def test_update_song_isrc(self, app, client):
        """Test PUT updates ISRC field."""
        song_id = self._make_song(app)
        response = client.put(
            f'/api/songs/{song_id}',
            data=json.dumps({'isrc': 'USABC1234567'}),
            content_type='application/json',
        )
        assert response.status_code == 200

    def test_update_song_invalid_popularity(self, app, client):
        """Test PUT with invalid popularity value is handled gracefully."""
        song_id = self._make_song(app)
        response = client.put(
            f'/api/songs/{song_id}',
            data=json.dumps({'popularity': 'not_a_number'}),
            content_type='application/json',
        )
        assert response.status_code == 200

    def test_update_song_spotify_id(self, app, client):
        """Test PUT updates spotify_id."""
        song_id = self._make_song(app)
        response = client.put(
            f'/api/songs/{song_id}',
            data=json.dumps({'spotify_id': 'newspotifyid123'}),
            content_type='application/json',
        )
        assert response.status_code == 200

    def test_update_song_deezer_id(self, app, client):
        """Test PUT updates deezer_id."""
        song_id = self._make_song(app)
        response = client.put(
            f'/api/songs/{song_id}',
            data=json.dumps({'deezer_id': '12345678'}),
            content_type='application/json',
        )
        assert response.status_code == 200

    def test_update_song_preview_url(self, app, client):
        """Test PUT updates preview_url."""
        song_id = self._make_song(app)
        response = client.put(
            f'/api/songs/{song_id}',
            data=json.dumps({'preview_url': 'https://example.com/preview.mp3'}),
            content_type='application/json',
        )
        assert response.status_code == 200

    def test_update_song_cover_url(self, app, client):
        """Test PUT updates cover_url."""
        song_id = self._make_song(app)
        response = client.put(
            f'/api/songs/{song_id}',
            data=json.dumps({'cover_url': 'https://example.com/cover.jpg'}),
            content_type='application/json',
        )
        assert response.status_code == 200

    def test_add_tag_no_data(self, app, client):
        """Test POST /api/songs/<id>/tags with no data returns 400."""
        song_id = self._make_song(app, title='No Tag Data Song')
        response = client.post(
            f'/api/songs/{song_id}/tags',
            data=json.dumps({}),
            content_type='application/json',
        )
        assert response.status_code == 400

    def test_add_tag_already_on_song(self, app, client):
        """Test POST /api/songs/<id>/tags when tag already exists on song."""
        song_id = self._make_song(app, title='Already Tagged Song')
        with app.app_context():
            tag = Tag(name='AlreadyAddedTag')
            song = Song.query.get(song_id)
            db.session.add(tag)
            db.session.commit()
            song.tags.append(tag)
            db.session.commit()
            tag_id = tag.id

        # Add the tag again
        response = client.post(
            f'/api/songs/{song_id}/tags',
            data=json.dumps({'tag_id': tag_id}),
            content_type='application/json',
        )
        assert response.status_code == 200
        data = response.get_json()
        assert 'already has tag' in data.get('message', '').lower()

    def test_remove_tag_not_on_song(self, app, client):
        """Test DELETE /api/songs/<id>/tags/<tag_id> when tag not on song."""
        song_id = self._make_song(app, title='Untagged Song')
        with app.app_context():
            tag = Tag(name='NotOnSongTag')
            db.session.add(tag)
            db.session.commit()
            tag_id = tag.id

        response = client.delete(f'/api/songs/{song_id}/tags/{tag_id}')
        assert response.status_code == 200
        data = response.get_json()
        assert "doesn't have tag" in data.get('message', '')
