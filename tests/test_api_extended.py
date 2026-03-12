"""Extended API endpoint tests."""
import pytest
import json
from musicround.models import db, User, Song, Tag


def _create_user_and_login(app, client, username='apiuser', email='api@example.com'):
    """Helper: create a user and log in."""
    with app.app_context():
        existing = User.query.filter_by(username=username).first()
        if not existing:
            user = User(username=username, email=email)
            user.password = 'ApiPass123!'
            db.session.add(user)
            db.session.commit()
    client.post('/users/login', data={'username': username, 'password': 'ApiPass123!'})


def _create_song(app, title='Test Song', artist='Test Artist', genre='Rock'):
    """Helper: create and persist a Song, returning its id."""
    with app.app_context():
        song = Song(title=title, artist=artist, genre=genre)
        db.session.add(song)
        db.session.commit()
        return song.id


class TestTagsApi:
    """Tests for /api/tags endpoints."""

    def test_get_tags_empty(self, app, client):
        """Test GET /api/tags returns empty tags list when no tags exist."""
        response = client.get('/api/tags')
        assert response.status_code == 200
        data = response.get_json()
        assert 'tags' in data
        assert data['tags'] == []

    def test_create_tag(self, app, client):
        """Test POST /api/tags creates a new tag."""
        _create_user_and_login(app, client, 'tagcreate', 'tagcreate@example.com')
        response = client.post(
            '/api/tags',
            data=json.dumps({'name': 'NewTag'}),
            content_type='application/json',
        )
        assert response.status_code == 201
        data = response.get_json()
        assert 'tag' in data
        assert data['tag']['name'] == 'NewTag'

    def test_create_tag_duplicate(self, app, client):
        """Test POST /api/tags returns existing tag if duplicate name."""
        _create_user_and_login(app, client, 'tagdup', 'tagdup@example.com')
        # Create first
        client.post('/api/tags', data=json.dumps({'name': 'DupTag'}),
                    content_type='application/json')
        # Create second with same name
        response = client.post('/api/tags', data=json.dumps({'name': 'DupTag'}),
                               content_type='application/json')
        # Should return 200 (existing tag, not 201)
        assert response.status_code == 200
        data = response.get_json()
        assert 'tag' in data

    def test_create_tag_missing_name(self, app, client):
        """Test POST /api/tags returns 400 when name is missing."""
        _create_user_and_login(app, client, 'tagnoname', 'tagnoname@example.com')
        response = client.post('/api/tags', data=json.dumps({}),
                               content_type='application/json')
        assert response.status_code == 400

    def test_get_tags_after_creation(self, app, client):
        """Test GET /api/tags returns created tags."""
        _create_user_and_login(app, client, 'taglist', 'taglist@example.com')
        # Create a tag
        with app.app_context():
            tag = Tag(name='ListableTag')
            db.session.add(tag)
            db.session.commit()

        response = client.get('/api/tags')
        data = response.get_json()
        tag_names = [t['name'] for t in data['tags']]
        assert 'ListableTag' in tag_names


class TestSongTagsApi:
    """Tests for /api/songs/<id>/tags endpoints."""

    def test_get_song_tags_empty(self, app, client):
        """Test GET /api/songs/<id>/tags returns empty list for song with no tags."""
        song_id = _create_song(app, 'TagSong1', 'Artist')
        response = client.get(f'/api/songs/{song_id}/tags')
        assert response.status_code == 200
        data = response.get_json()
        assert 'tags' in data
        assert data['tags'] == []

    def test_add_tag_to_song(self, app, client):
        """Test POST /api/songs/<id>/tags adds a tag to a song."""
        _create_user_and_login(app, client, 'addtaguser', 'addtag@example.com')
        song_id = _create_song(app, 'TagSong2', 'Artist2')

        # Create a tag first
        with app.app_context():
            tag = Tag(name='AddableTag')
            db.session.add(tag)
            db.session.commit()
            tag_id = tag.id

        response = client.post(
            f'/api/songs/{song_id}/tags',
            data=json.dumps({'tag_id': tag_id}),
            content_type='application/json',
        )
        assert response.status_code in (200, 201)

    def test_add_tag_by_name(self, app, client):
        """Test POST /api/songs/<id>/tags creates and adds tag by name."""
        _create_user_and_login(app, client, 'tagbynameuser', 'tagbyname@example.com')
        song_id = _create_song(app, 'TagSong3', 'Artist3')
        response = client.post(
            f'/api/songs/{song_id}/tags',
            data=json.dumps({'tag_name': 'BrandNewTag'}),
            content_type='application/json',
        )
        assert response.status_code in (200, 201)

    def test_get_songs_by_tag(self, app, client):
        """Test GET /api/tags/<tag_id> returns songs for that tag."""
        with app.app_context():
            tag = Tag(name='SongsByTag')
            song = Song(title='Tagged Song', artist='Artist', genre='Pop')
            db.session.add_all([tag, song])
            db.session.commit()
            song.tags.append(tag)
            db.session.commit()
            tag_id = tag.id

        response = client.get(f'/api/tags/{tag_id}')
        assert response.status_code == 200

    def test_remove_tag_from_song(self, app, client):
        """Test DELETE /api/songs/<id>/tags/<tag_id> removes a tag."""
        _create_user_and_login(app, client, 'removetaguser', 'removetag@example.com')
        with app.app_context():
            tag = Tag(name='RemovableTag')
            song = Song(title='RemoveTagSong', artist='A', genre='Pop')
            db.session.add_all([tag, song])
            db.session.commit()
            song.tags.append(tag)
            db.session.commit()
            song_id = song.id
            tag_id = tag.id

        response = client.delete(f'/api/songs/{song_id}/tags/{tag_id}')
        assert response.status_code in (200, 204)


class TestSongSearchApi:
    """Tests for /api/songs/search endpoint."""

    def test_search_songs_authenticated(self, app, client):
        """Test song search returns results when authenticated."""
        _create_user_and_login(app, client, 'searchapiuser', 'searchapi@example.com')
        # Create songs to search
        with app.app_context():
            songs = [
                Song(title='Searchable Rock Song', artist='Rock Band', genre='Rock'),
                Song(title='Another Pop Song', artist='Pop Star', genre='Pop'),
            ]
            db.session.add_all(songs)
            db.session.commit()

        response = client.get('/api/songs/search?q=Rock')
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)
        assert any('Rock' in song.get('title', '') or 'Rock' in song.get('artist', '')
                   for song in data)

    def test_search_songs_short_query(self, app, client):
        """Test song search returns empty for too-short query."""
        _create_user_and_login(app, client, 'shortquery', 'shortq@example.com')
        response = client.get('/api/songs/search?q=r')
        assert response.status_code == 200
        data = response.get_json()
        assert data == []

    def test_search_songs_empty_query(self, app, client):
        """Test song search returns empty for no query."""
        _create_user_and_login(app, client, 'emptyquery', 'emptyq@example.com')
        response = client.get('/api/songs/search?q=')
        assert response.status_code == 200
        data = response.get_json()
        assert data == []

    def test_search_songs_by_artist(self, app, client):
        """Test song search works for artist name."""
        _create_user_and_login(app, client, 'artistsearch', 'artistsearch@example.com')
        with app.app_context():
            song = Song(title='Unique Title XYZ', artist='SpecificArtistABC', genre='Jazz')
            db.session.add(song)
            db.session.commit()

        response = client.get('/api/songs/search?q=SpecificArtistABC')
        assert response.status_code == 200
        data = response.get_json()
        assert len(data) >= 1
        assert any(s['artist'] == 'SpecificArtistABC' for s in data)
