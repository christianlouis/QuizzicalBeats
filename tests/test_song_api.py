"""Tests for song API CRUD endpoints."""
import pytest
import json
from musicround.models import db, User, Song, Round


def _login(app, client, username='songapiuser', email='songapi@example.com'):
    """Helper: create and log in a user."""
    with app.app_context():
        existing = User.query.filter_by(username=username).first()
        if not existing:
            user = User(username=username, email=email)
            user.password = 'SongApiPass123!'
            db.session.add(user)
            db.session.commit()
    client.post('/users/login', data={'username': username, 'password': 'SongApiPass123!'})


def _create_song(app, **kwargs):
    """Helper: create a song and return its id."""
    defaults = {'title': 'API Test Song', 'artist': 'API Artist', 'genre': 'Rock'}
    defaults.update(kwargs)
    with app.app_context():
        song = Song(**defaults)
        db.session.add(song)
        db.session.commit()
        return song.id


class TestSongDetailGet:
    """Tests for GET /api/songs/<id>."""

    def test_get_song_not_found(self, app, client):
        """Test GET returns 404 for non-existent song."""
        response = client.get('/api/songs/99999')
        assert response.status_code == 404

    def test_get_song_success(self, app, client):
        """Test GET returns song details."""
        song_id = _create_song(app, title='Get Test Song', artist='Get Artist', genre='Pop',
                               year=2000, spotify_id='gettest123')
        response = client.get(f'/api/songs/{song_id}')
        assert response.status_code == 200
        data = response.get_json()
        assert data['title'] == 'Get Test Song'
        assert data['artist'] == 'Get Artist'
        assert data['id'] == song_id

    def test_get_song_has_all_fields(self, app, client):
        """Test GET returns all expected fields."""
        song_id = _create_song(app)
        response = client.get(f'/api/songs/{song_id}')
        data = response.get_json()
        expected_fields = ['id', 'title', 'artist', 'genre', 'year', 'isrc',
                           'preview_url', 'cover_url', 'tags', 'acousticness',
                           'danceability', 'energy', 'tempo']
        for field in expected_fields:
            assert field in data, f"Field '{field}' missing from response"

    def test_get_song_has_audio_features(self, app, client):
        """Test GET song includes audio features."""
        song_id = _create_song(app, danceability=0.8, energy=0.9, tempo=120.0)
        response = client.get(f'/api/songs/{song_id}')
        data = response.get_json()
        assert data['danceability'] == 0.8
        assert data['energy'] == 0.9
        assert data['tempo'] == 120.0


class TestSongDetailPut:
    """Tests for PUT /api/songs/<id>."""

    def test_update_song_title(self, app, client):
        """Test PUT updates song title."""
        song_id = _create_song(app, title='Original Title')
        response = client.put(
            f'/api/songs/{song_id}',
            data=json.dumps({'title': 'Updated Title'}),
            content_type='application/json',
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['title'] == 'Updated Title'

    def test_update_song_artist(self, app, client):
        """Test PUT updates song artist."""
        song_id = _create_song(app, artist='Original Artist')
        response = client.put(
            f'/api/songs/{song_id}',
            data=json.dumps({'artist': 'New Artist'}),
            content_type='application/json',
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['artist'] == 'New Artist'

    def test_update_song_genre(self, app, client):
        """Test PUT updates song genre."""
        song_id = _create_song(app, genre='Rock')
        response = client.put(
            f'/api/songs/{song_id}',
            data=json.dumps({'genre': 'Jazz'}),
            content_type='application/json',
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['genre'] == 'Jazz'

    def test_update_song_year(self, app, client):
        """Test PUT updates song year."""
        song_id = _create_song(app, year=2000)
        response = client.put(
            f'/api/songs/{song_id}',
            data=json.dumps({'year': 2020}),
            content_type='application/json',
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['year'] == 2020

    def test_update_song_popularity(self, app, client):
        """Test PUT updates song popularity."""
        song_id = _create_song(app)
        response = client.put(
            f'/api/songs/{song_id}',
            data=json.dumps({'popularity': 85}),
            content_type='application/json',
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['popularity'] == 85

    def test_update_song_not_found(self, app, client):
        """Test PUT on non-existent song returns 404."""
        response = client.put(
            '/api/songs/99999',
            data=json.dumps({'title': 'Test'}),
            content_type='application/json',
        )
        assert response.status_code == 404

    def test_update_song_persists_to_db(self, app, client):
        """Test PUT changes are persisted to the database."""
        song_id = _create_song(app, title='Before Update', artist='Orig')
        client.put(
            f'/api/songs/{song_id}',
            data=json.dumps({'title': 'After Update'}),
            content_type='application/json',
        )
        with app.app_context():
            song = Song.query.get(song_id)
            assert song.title == 'After Update'

    def test_update_song_partial_update(self, app, client):
        """Test PUT with partial data only updates specified fields."""
        song_id = _create_song(app, title='Keep Title', artist='Keep Artist', genre='Keep Genre')
        client.put(
            f'/api/songs/{song_id}',
            data=json.dumps({'genre': 'New Genre'}),
            content_type='application/json',
        )
        with app.app_context():
            song = Song.query.get(song_id)
            assert song.title == 'Keep Title'
            assert song.artist == 'Keep Artist'
            assert song.genre == 'New Genre'


class TestSongDetailDelete:
    """Tests for DELETE /api/songs/<id>."""

    def test_delete_song_not_found(self, app, client):
        """Test DELETE on non-existent song returns 404."""
        response = client.delete('/api/songs/99999')
        assert response.status_code == 404

    def test_delete_song_success(self, app, client):
        """Test DELETE successfully removes a song."""
        song_id = _create_song(app, title='Delete Me Song')
        response = client.delete(f'/api/songs/{song_id}')
        assert response.status_code == 200
        data = response.get_json()
        assert 'deleted' in data.get('message', '').lower() or data.get('id') == song_id

        # Verify song is gone from db
        with app.app_context():
            song = Song.query.get(song_id)
            assert song is None

    def test_delete_song_in_use_fails(self, app, client):
        """Test DELETE on a song used in a round returns 400."""
        song_id = _create_song(app, title='In-Use Song')
        with app.app_context():
            round_ = Round(
                round_type='genre', round_criteria_used='Rock',
                songs=str(song_id),
            )
            db.session.add(round_)
            db.session.commit()

        response = client.delete(f'/api/songs/{song_id}')
        assert response.status_code == 400
        data = response.get_json()
        assert 'error' in data
