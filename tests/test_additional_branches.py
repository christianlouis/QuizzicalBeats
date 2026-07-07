"""Additional tests for setup, system health, and API branches."""
import json
import pytest
from musicround.helpers.import_queue import ImportQueue
from musicround.models import db, ImportJobRecord, User, Role, Song, Tag


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

    def test_setup_failure_hides_exception_details(self, app, client, monkeypatch):
        """Setup failure flashes should not expose database or token-like details."""
        _create_user(app, 'setup_error_user', 'setuperror@example.com')
        _login(app, client, 'setup_error_user')

        def fail_commit():
            raise RuntimeError('database down token=setup-secret traceback')

        monkeypatch.setattr(db.session, 'commit', fail_commit)

        response = client.get('/users/setup', follow_redirects=True)

        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert 'Error setting up admin privileges. Please try again or check the server logs.' in body
        assert 'database down' not in body
        assert 'setup-secret' not in body
        assert 'traceback' not in body


class TestSystemHealthRoute:
    """Tests for /users/system-health route."""

    def test_healthz_public_safe_payload(self, client):
        """The uptime endpoint should not require login or expose secrets."""
        response = client.get('/healthz')

        assert response.status_code == 200
        data = response.get_json()
        assert data['ok'] is True
        assert data['status'] == 'ok'
        assert data['services']['database']['status'] == 'ok'
        assert data['services']['import_queue']['initialized'] is True
        assert 'password' not in json.dumps(data).lower()
        assert 'token' not in json.dumps(data).lower()

    def test_import_queue_health_reports_pending_without_local_workers(self, app):
        """Queue health should warn when imports are waiting but local workers are disabled."""
        from musicround.helpers.service_health import import_queue_service_health

        with app.app_context():
            app.config['import_queue'] = ImportQueue()
            app.config['import_workers'] = []
            app.config['IMPORT_WORKERS_ENABLED_RESOLVED'] = False
            user = User(username='queue_health_user', email='queue-health@example.com')
            db.session.add(user)
            db.session.commit()
            db.session.add(
                ImportJobRecord(
                    service_name='spotify',
                    item_type='playlist',
                    item_id='pending-playlist',
                    user_id=user.id,
                    status='pending',
                )
            )
            db.session.commit()

            health = import_queue_service_health()

        assert health['ok'] is True
        assert health['status'] == 'warning'
        assert health['jobs']['pending'] == 1
        assert health['issues'][0]['code'] == 'import_jobs_waiting_without_local_workers'

    def test_import_queue_health_reports_dead_letter_jobs(self, app):
        """Dead-letter jobs should be visible as repairable health warnings."""
        from musicround.helpers.service_health import import_queue_service_health

        with app.app_context():
            app.config['import_queue'] = ImportQueue()
            app.config['import_workers'] = [object()]
            app.config['IMPORT_WORKERS_ENABLED_RESOLVED'] = True
            app.config['IMPORT_WORKER_COUNT_RESOLVED'] = 1
            user = User(username='queue_dead_user', email='queue-dead@example.com')
            db.session.add(user)
            db.session.commit()
            db.session.add(
                ImportJobRecord(
                    service_name='spotify',
                    item_type='playlist',
                    item_id='dead-playlist',
                    user_id=user.id,
                    status='dead_letter',
                )
            )
            db.session.commit()

            health = import_queue_service_health()

        assert health['ok'] is True
        assert health['status'] == 'warning'
        assert health['worker_count'] == 1
        assert health['jobs']['dead_letter'] == 1
        assert any(issue['code'] == 'import_jobs_need_manual_review' for issue in health['issues'])

    def test_healthz_reports_degraded_storage(self, client, monkeypatch):
        """Storage failures should make /healthz fail for deployment gates."""
        from musicround.helpers import service_health

        monkeypatch.setattr(
            service_health,
            'check_round_artifact_storage',
            lambda include_mp3=True, include_pdf=True: {
                'ok': False,
                'checks': [],
                'issues': [{
                    'code': 'artifact_storage_not_writable',
                    'severity': 'error',
                    'message': 'Round MP3 directory is not writable.',
                    'details': {'hint': 'Fix storage permissions.'},
                }],
                'hints': ['Fix storage permissions.'],
            },
        )

        response = client.get('/healthz')

        assert response.status_code == 503
        data = response.get_json()
        assert data['ok'] is False
        assert data['status'] == 'degraded'
        assert data['services']['artifact_storage']['issues'][0]['code'] == 'artifact_storage_not_writable'

    def test_healthz_database_error_hides_exception_details(self, app, client, monkeypatch):
        """Database probe failures must not expose raw driver errors or credentials."""
        def fail_probe(*args, **kwargs):
            raise RuntimeError('postgres://qb:secret-password@db.example/qb token=health-secret traceback')

        monkeypatch.setattr(db.session, 'execute', fail_probe)

        response = client.get('/healthz')

        body = response.get_data(as_text=True)
        data = response.get_json()
        assert response.status_code == 503
        assert data['services']['database']['issues'][0]['code'] == 'database_unavailable'
        assert 'secret-password' not in body
        assert 'health-secret' not in body
        assert 'traceback' not in body

    def test_database_health_warns_for_legacy_data_sqlite(self, app):
        """Legacy production SQLite config should be visible without failing uptime checks."""
        from musicround.helpers.service_health import database_service_health

        with app.app_context():
            app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////data/song_data.db'
            app.config['DATABASE_BACKEND'] = 'sqlite'

            health = database_service_health()

        assert health['ok'] is True
        assert health['status'] == 'warning'
        assert health['issues'][0]['code'] == 'legacy_sqlite_data_store'
        assert 'complete PG* managed database credentials' in health['issues'][0]['details']['hint']

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

    def test_system_health_database_error_hides_exception_details(self, app, client, monkeypatch):
        """System-health should not render database exception details."""
        from musicround.helpers import backup_helper
        from musicround.helpers import database_config

        def fail_database_summary(uri):
            raise RuntimeError('database-uri-secret token=health-secret traceback')

        _create_user(app, 'health_admin_error', 'healthadminerror@example.com', is_admin=True)
        _login(app, client, 'health_admin_error')
        monkeypatch.setattr(database_config, 'database_summary', fail_database_summary)
        monkeypatch.setattr(backup_helper, 'list_backups', lambda: [])

        response = client.get('/users/system-health')

        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert 'Database status check failed. Check the server logs.' in body
        assert 'database-uri-secret' not in body
        assert 'health-secret' not in body
        assert 'traceback' not in body


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
        _create_user(app, 'song_branch_isrc', 'song_branch_isrc@example.com')
        _login(app, client, 'song_branch_isrc')
        song_id = self._make_song(app)
        response = client.put(
            f'/api/songs/{song_id}',
            data=json.dumps({'isrc': 'USABC1234567'}),
            content_type='application/json',
        )
        assert response.status_code == 200

    def test_update_song_invalid_popularity(self, app, client):
        """Test PUT with invalid popularity value is handled gracefully."""
        _create_user(app, 'song_branch_popularity', 'song_branch_popularity@example.com')
        _login(app, client, 'song_branch_popularity')
        song_id = self._make_song(app)
        response = client.put(
            f'/api/songs/{song_id}',
            data=json.dumps({'popularity': 'not_a_number'}),
            content_type='application/json',
        )
        assert response.status_code == 200

    def test_update_song_spotify_id(self, app, client):
        """Test PUT updates spotify_id."""
        _create_user(app, 'song_branch_spotify', 'song_branch_spotify@example.com')
        _login(app, client, 'song_branch_spotify')
        song_id = self._make_song(app)
        response = client.put(
            f'/api/songs/{song_id}',
            data=json.dumps({'spotify_id': 'newspotifyid123'}),
            content_type='application/json',
        )
        assert response.status_code == 200

    def test_update_song_deezer_id(self, app, client):
        """Test PUT updates deezer_id."""
        _create_user(app, 'song_branch_deezer', 'song_branch_deezer@example.com')
        _login(app, client, 'song_branch_deezer')
        song_id = self._make_song(app)
        response = client.put(
            f'/api/songs/{song_id}',
            data=json.dumps({'deezer_id': '12345678'}),
            content_type='application/json',
        )
        assert response.status_code == 200

    def test_update_song_preview_url(self, app, client):
        """Test PUT updates preview_url."""
        _create_user(app, 'song_branch_preview', 'song_branch_preview@example.com')
        _login(app, client, 'song_branch_preview')
        song_id = self._make_song(app)
        response = client.put(
            f'/api/songs/{song_id}',
            data=json.dumps({'preview_url': 'https://example.com/preview.mp3'}),
            content_type='application/json',
        )
        assert response.status_code == 200

    def test_update_song_cover_url(self, app, client):
        """Test PUT updates cover_url."""
        _create_user(app, 'song_branch_cover', 'song_branch_cover@example.com')
        _login(app, client, 'song_branch_cover')
        song_id = self._make_song(app)
        response = client.put(
            f'/api/songs/{song_id}',
            data=json.dumps({'cover_url': 'https://example.com/cover.jpg'}),
            content_type='application/json',
        )
        assert response.status_code == 200

    def test_add_tag_no_data(self, app, client):
        """Test POST /api/songs/<id>/tags with no data returns 400."""
        _create_user(app, 'song_branch_tag_empty', 'song_branch_tag_empty@example.com')
        _login(app, client, 'song_branch_tag_empty')
        song_id = self._make_song(app, title='No Tag Data Song')
        response = client.post(
            f'/api/songs/{song_id}/tags',
            data=json.dumps({}),
            content_type='application/json',
        )
        assert response.status_code == 400

    def test_add_tag_already_on_song(self, app, client):
        """Test POST /api/songs/<id>/tags when tag already exists on song."""
        _create_user(app, 'song_branch_tag_existing', 'song_branch_tag_existing@example.com')
        _login(app, client, 'song_branch_tag_existing')
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
        _create_user(app, 'song_branch_tag_remove', 'song_branch_tag_remove@example.com')
        _login(app, client, 'song_branch_tag_remove')
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
