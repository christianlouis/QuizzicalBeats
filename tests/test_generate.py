"""Tests for generate blueprint helper functions and routes."""
import pytest
from musicround.models import db, User, Song, Round, Tag


def _login(app, client, username='genuser', email='gen@example.com'):
    """Helper: create and log in a user."""
    with app.app_context():
        existing = User.query.filter_by(username=username).first()
        if not existing:
            user = User(username=username, email=email)
            user.password = 'GenPass123!'
            db.session.add(user)
            db.session.commit()
    client.post('/users/login', data={'username': username, 'password': 'GenPass123!'})


def _add_songs(app, songs_data):
    """Helper: add songs to the database."""
    with app.app_context():
        for data in songs_data:
            song = Song(**data)
            db.session.add(song)
        db.session.commit()


class TestGetAllDecades:
    """Tests for generate.get_all_decades helper."""

    def test_empty_db(self, app):
        """Test get_all_decades returns empty list when no songs exist."""
        from musicround.routes.generate import get_all_decades
        with app.app_context():
            result = get_all_decades()
        assert result == []

    def test_single_decade(self, app):
        """Test get_all_decades returns correct decade for one song."""
        from musicround.routes.generate import get_all_decades
        _add_songs(app, [{'title': 'Song', 'artist': 'A', 'genre': 'Rock', 'year': 1985}])
        with app.app_context():
            result = get_all_decades()
        assert '1980' in result

    def test_multiple_decades(self, app):
        """Test get_all_decades returns multiple unique decades."""
        from musicround.routes.generate import get_all_decades
        _add_songs(app, [
            {'title': 'S1', 'artist': 'A', 'genre': 'Rock', 'year': 1975},
            {'title': 'S2', 'artist': 'B', 'genre': 'Pop', 'year': 1985},
            {'title': 'S3', 'artist': 'C', 'genre': 'Jazz', 'year': 1995},
        ])
        with app.app_context():
            result = get_all_decades()
        assert '1970' in result
        assert '1980' in result
        assert '1990' in result

    def test_duplicate_decades_collapsed(self, app):
        """Test that songs in the same decade appear only once."""
        from musicround.routes.generate import get_all_decades
        _add_songs(app, [
            {'title': 'S1', 'artist': 'A', 'genre': 'Rock', 'year': 1981},
            {'title': 'S2', 'artist': 'B', 'genre': 'Rock', 'year': 1989},
        ])
        with app.app_context():
            result = get_all_decades()
        assert result.count('1980') == 1

    def test_songs_without_year_excluded(self, app):
        """Test that songs without a year are excluded."""
        from musicround.routes.generate import get_all_decades
        _add_songs(app, [{'title': 'No Year', 'artist': 'A', 'genre': 'Rock', 'year': None}])
        with app.app_context():
            result = get_all_decades()
        assert result == []


class TestGetAllGenres:
    """Tests for generate.get_all_genres helper."""

    def test_empty_db(self, app):
        """Test get_all_genres returns empty list when no songs exist."""
        from musicround.routes.generate import get_all_genres
        with app.app_context():
            result = get_all_genres()
        assert result == []

    def test_single_genre(self, app):
        """Test get_all_genres with one genre."""
        from musicround.routes.generate import get_all_genres
        _add_songs(app, [{'title': 'S1', 'artist': 'A', 'genre': 'Jazz', 'year': 2000}])
        with app.app_context():
            result = get_all_genres()
        assert 'Jazz' in result

    def test_multiple_genres(self, app):
        """Test get_all_genres with multiple different genres."""
        from musicround.routes.generate import get_all_genres
        _add_songs(app, [
            {'title': 'S1', 'artist': 'A', 'genre': 'Rock', 'year': 2000},
            {'title': 'S2', 'artist': 'B', 'genre': 'Pop', 'year': 2001},
            {'title': 'S3', 'artist': 'C', 'genre': 'Jazz', 'year': 2002},
        ])
        with app.app_context():
            result = get_all_genres()
        assert 'Rock' in result
        assert 'Pop' in result
        assert 'Jazz' in result

    def test_duplicate_genres_collapsed(self, app):
        """Test that duplicate genres appear only once."""
        from musicround.routes.generate import get_all_genres
        _add_songs(app, [
            {'title': 'S1', 'artist': 'A', 'genre': 'Rock', 'year': 2000},
            {'title': 'S2', 'artist': 'B', 'genre': 'Rock', 'year': 2001},
        ])
        with app.app_context():
            result = get_all_genres()
        assert result.count('Rock') == 1


class TestGetAllTags:
    """Tests for generate.get_all_tags helper."""

    def test_empty_db(self, app):
        """Test get_all_tags returns empty list when no tags exist."""
        from musicround.routes.generate import get_all_tags
        with app.app_context():
            result = get_all_tags()
        assert result == []

    def test_with_tags(self, app):
        """Test get_all_tags returns tag names."""
        from musicround.routes.generate import get_all_tags
        with app.app_context():
            tag1 = Tag(name='Classic')
            tag2 = Tag(name='Modern')
            db.session.add_all([tag1, tag2])
            db.session.commit()

            result = get_all_tags()
        assert 'Classic' in result
        assert 'Modern' in result


class TestGetSongsByTag:
    """Tests for generate.get_songs_by_tag helper."""

    def test_no_such_tag(self, app):
        """Test get_songs_by_tag returns empty list for non-existent tag."""
        from musicround.routes.generate import get_songs_by_tag
        with app.app_context():
            result = get_songs_by_tag('NonExistentTag')
        assert result == []

    def test_tag_with_songs(self, app):
        """Test get_songs_by_tag returns songs for a given tag."""
        from musicround.routes.generate import get_songs_by_tag
        with app.app_context():
            tag = Tag(name='TestTagGen')
            song = Song(title='Tagged Generate Song', artist='A', genre='Pop')
            db.session.add_all([tag, song])
            db.session.commit()
            song.tags.append(tag)
            db.session.commit()

            result = get_songs_by_tag('TestTagGen')
        assert len(result) == 1
        assert result[0].title == 'Tagged Generate Song'

    def test_respects_limit(self, app):
        """Test get_songs_by_tag respects the limit parameter."""
        from musicround.routes.generate import get_songs_by_tag
        with app.app_context():
            tag = Tag(name='LimitTag')
            db.session.add(tag)
            db.session.commit()
            for i in range(5):
                song = Song(title=f'LimitSong {i}', artist='A', genre='Pop')
                db.session.add(song)
                db.session.commit()
                song.tags.append(tag)
            db.session.commit()

            result = get_songs_by_tag('LimitTag', limit=3)
        assert len(result) <= 3


class TestGetLeastUsedGenres:
    """Tests for generate.get_least_used_genres helper."""

    def test_empty_db(self, app):
        """Test get_least_used_genres with no songs returns empty list."""
        from musicround.routes.generate import get_least_used_genres
        with app.app_context():
            result = get_least_used_genres()
        assert result == []

    def test_all_genres_unused(self, app):
        """Test all genres returned when none have been used in rounds."""
        from musicround.routes.generate import get_least_used_genres
        _add_songs(app, [
            {'title': 'S1', 'artist': 'A', 'genre': 'Rock', 'year': 2000},
            {'title': 'S2', 'artist': 'B', 'genre': 'Pop', 'year': 2001},
        ])
        with app.app_context():
            result = get_least_used_genres()
        assert 'Rock' in result
        assert 'Pop' in result


class TestGetLeastUsedDecades:
    """Tests for generate.get_least_used_decades helper."""

    def test_empty_db(self, app):
        """Test get_least_used_decades with no songs returns empty list."""
        from musicround.routes.generate import get_least_used_decades
        with app.app_context():
            result = get_least_used_decades()
        assert result == []

    def test_all_decades_unused(self, app):
        """Test all decades returned when none have been used in rounds."""
        from musicround.routes.generate import get_least_used_decades
        _add_songs(app, [
            {'title': 'S1', 'artist': 'A', 'genre': 'Rock', 'year': 1980},
            {'title': 'S2', 'artist': 'B', 'genre': 'Pop', 'year': 1990},
        ])
        with app.app_context():
            result = get_least_used_decades()
        assert '1980' in result
        assert '1990' in result


class TestGetLeastUsedSongs:
    """Tests for generate.get_least_used_songs helper."""

    def test_empty_db(self, app):
        """Test returns empty list when no songs exist."""
        from musicround.routes.generate import get_least_used_songs
        with app.app_context():
            result = get_least_used_songs()
        assert result == []

    def test_returns_songs(self, app):
        """Test returns songs that have never been used in a round."""
        from musicround.routes.generate import get_least_used_songs
        _add_songs(app, [
            {'title': 'Unused Song', 'artist': 'A', 'genre': 'Rock', 'year': 2000},
        ])
        with app.app_context():
            result = get_least_used_songs()
        assert len(result) == 1

    def test_filter_by_genre(self, app):
        """Test filtering by genre."""
        from musicround.routes.generate import get_least_used_songs
        _add_songs(app, [
            {'title': 'Rock Song', 'artist': 'A', 'genre': 'Rock', 'year': 2000},
            {'title': 'Pop Song', 'artist': 'B', 'genre': 'Pop', 'year': 2001},
        ])
        with app.app_context():
            result = get_least_used_songs(genre='Rock')
        assert all(s.genre == 'Rock' for s in result)

    def test_filter_by_decade(self, app):
        """Test filtering by decade."""
        from musicround.routes.generate import get_least_used_songs
        _add_songs(app, [
            {'title': '80s Song', 'artist': 'A', 'genre': 'Rock', 'year': 1985},
            {'title': '90s Song', 'artist': 'B', 'genre': 'Pop', 'year': 1995},
        ])
        with app.app_context():
            result = get_least_used_songs(decade='1980')
        assert all(s.year and str(s.year)[:3] + '0' == '1980' for s in result)


class TestGetNonOverusedSongs:
    """Tests for generate.get_non_overused_songs helper."""

    def test_empty_db(self, app):
        """Test returns empty list when no songs exist."""
        from musicround.routes.generate import get_non_overused_songs
        with app.app_context():
            result = get_non_overused_songs()
        assert result == []

    def test_returns_songs(self, app):
        """Test returns songs when they exist."""
        from musicround.routes.generate import get_non_overused_songs
        _add_songs(app, [
            {'title': 'S1', 'artist': 'A', 'genre': 'Rock', 'year': 2000},
        ])
        with app.app_context():
            result = get_non_overused_songs()
        assert len(result) == 1


class TestGetRandomSongs:
    """Tests for generate.get_random_songs helper."""

    def test_empty_db(self, app):
        """Test returns empty list when no songs exist."""
        from musicround.routes.generate import get_random_songs
        with app.app_context():
            result = get_random_songs(5)
        assert result == []

    def test_fewer_songs_than_requested(self, app):
        """Test returns all available songs when fewer exist than requested."""
        from musicround.routes.generate import get_random_songs
        _add_songs(app, [
            {'title': 'Only Song', 'artist': 'A', 'genre': 'Rock', 'year': 2000},
        ])
        with app.app_context():
            result = get_random_songs(5)
        assert len(result) <= 5


class TestBuildMusicRoundRoute:
    """Tests for the /build-music-round route."""

    def test_build_round_get_requires_login(self, client):
        """Test that the build-music-round page requires authentication."""
        response = client.get('/build-music-round')
        assert response.status_code == 302
        assert 'login' in response.headers['Location'].lower()

    def test_build_round_get_authenticated(self, app, client):
        """Test that the build-music-round page loads when authenticated."""
        _login(app, client)
        response = client.get('/build-music-round')
        assert response.status_code == 200
