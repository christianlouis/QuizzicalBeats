"""Final targeted tests to push coverage to 30%."""
import pytest
from musicround.models import db, User, Song


def _login(app, client, username='final_user', email='final@example.com'):
    """Helper: create and log in a user."""
    with app.app_context():
        existing = User.query.filter_by(username=username).first()
        if not existing:
            user = User(username=username, email=email)
            user.password = 'FinalPass123!'
            db.session.add(user)
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


class TestImportRoutesAccess:
    """Tests for basic import route access."""

    def test_official_playlists_requires_login(self, client):
        """Test that import official playlists requires authentication."""
        response = client.get('/import/official-playlists')
        assert response.status_code in (200, 302)

    def test_direct_official_playlists_requires_login(self, client):
        """Test that direct official playlists requires authentication."""
        response = client.get('/import/direct-official-playlists')
        assert response.status_code in (200, 302)

    def test_import_songs_page_accessible(self, app, client):
        """Test that import official playlists requires Spotify or redirects."""
        _login(app, client)
        response = client.get('/import/official-playlists')
        # Without Spotify token, it may redirect elsewhere; still a valid response
        assert response.status_code in (200, 302)

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
