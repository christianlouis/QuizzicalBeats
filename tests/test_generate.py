"""Tests for generate blueprint helper functions and routes."""
from types import SimpleNamespace

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

    def test_zero_year_excluded(self, app):
        """Test that a zero year sentinel does not create a fake decade."""
        from musicround.routes.generate import get_all_decades
        _add_songs(app, [{'title': 'Zero Year', 'artist': 'A', 'genre': 'Rock', 'year': 0}])
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

    def test_normalizes_and_deduplicates_tags(self, app):
        """Test get_all_tags normalizes whitespace and duplicate casing."""
        from musicround.routes.generate import get_all_tags
        with app.app_context():
            db.session.add_all([
                Tag(name=' rock '),
                Tag(name='Rock'),
                Tag(name='Country'),
                Tag(name='hip hop'),
            ])
            db.session.commit()

            result = get_all_tags()

        assert result == ['Country', 'Hip-Hop', 'Rock']

    def test_filters_internal_and_noisy_tags(self, app):
        """Builder tags should hide import internals and obvious free-text noise."""
        from musicround.routes.generate import get_all_tags
        with app.app_context():
            db.session.add_all([
                Tag(name='seed:wacken-2026'),
                Tag(name='source:billboard'),
                Tag(name='https://example.test/playlist'),
                Tag(name='not actually a usable quiz tag'),
                Tag(name='Metal'),
                Tag(name='Pop'),
            ])
            db.session.commit()

            result = get_all_tags()

        assert result == ['Metal', 'Pop']


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

    def test_matches_normalized_tag_name(self, app):
        """Test get_songs_by_tag matches tags after trimming and lowercasing."""
        from musicround.routes.generate import get_songs_by_tag
        with app.app_context():
            tag1 = Tag(name=' rock ')
            tag2 = Tag(name='Rock')
            song1 = Song(title='Trimmed Rock Song', artist='A', genre='Rock')
            song2 = Song(title='Cased Rock Song', artist='B', genre='Rock')
            db.session.add_all([tag1, tag2, song1, song2])
            db.session.commit()
            song1.tags.append(tag1)
            song2.tags.append(tag2)
            db.session.commit()

            result = get_songs_by_tag('ROCK')

        assert {song.title for song in result} == {'Trimmed Rock Song', 'Cased Rock Song'}

    def test_matches_public_tag_aliases(self, app):
        """Test public tag aliases resolve to raw imported tag variants."""
        from musicround.routes.generate import get_songs_by_tag
        with app.app_context():
            tag = Tag(name='hip hop')
            song = Song(title='Alias Tag Song', artist='A', genre='Hip-Hop')
            db.session.add_all([tag, song])
            db.session.commit()
            song.tags.append(tag)
            db.session.commit()

            result = get_songs_by_tag('Hip-Hop')

        assert [song.title for song in result] == ['Alias Tag Song']

    def test_rejects_internal_tag_round_selection(self, app):
        """Internal tags should not be selectable even if they exist in storage."""
        from musicround.routes.generate import get_songs_by_tag
        with app.app_context():
            tag = Tag(name='seed:wacken')
            song = Song(title='Internal Tag Song', artist='A', genre='Metal')
            db.session.add_all([tag, song])
            db.session.commit()
            song.tags.append(tag)
            db.session.commit()

            result = get_songs_by_tag('seed:wacken')

        assert result == []

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

    def test_impossible_artist_diversity_returns_unique_songs(self, app):
        """Test impossible artist diversity does not hang or duplicate songs."""
        from musicround.routes.generate import get_random_songs
        _add_songs(app, [
            {'title': f'Same Artist {i}', 'artist': 'One Artist', 'genre': 'Rock', 'year': 1980 + i}
            for i in range(8)
        ])

        with app.app_context():
            result = get_random_songs(5)

        assert len(result) == 5
        assert len({song.id for song in result}) == 5

    def test_genre_fallback_does_not_duplicate_only_candidate(self, app):
        """Test narrow genre fallback never returns the same song twice."""
        from musicround.routes.generate import get_random_songs_from_genre
        _add_songs(app, [
            {'title': 'Only Jazz', 'artist': 'Solo', 'genre': 'Jazz', 'year': 1990},
        ])

        with app.app_context():
            result = get_random_songs_from_genre('Jazz', x=2)

        assert len(result) == 1
        assert len({song.id for song in result}) == len(result)

    def test_decade_fallback_does_not_duplicate_only_candidate(self, app):
        """Test narrow decade fallback never returns the same song twice."""
        from musicround.routes.generate import get_random_songs_from_decade
        _add_songs(app, [
            {'title': 'Only Eighties', 'artist': 'Solo', 'genre': 'Pop', 'year': 1984},
        ])

        with app.app_context():
            result = get_random_songs_from_decade('1980', x=2)

        assert len(result) == 1
        assert len({song.id for song in result}) == len(result)


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

    def test_import_deezer_playlist_returns_imported_songs(self, app, client, monkeypatch):
        """Test Deezer playlist imports from the Generate page return songs for review."""
        with app.app_context():
            app.config['deezer'] = object()
            app.config['SONGS_PER_ROUND'] = 2
            second_song = Song(title='Second In Database', artist='Artist B', deezer_id=501, source='deezer')
            first_song = Song(title='First In Playlist', artist='Artist A', deezer_id=502, source='deezer')
            missing_from_playlist = Song(title='Not In Playlist', artist='Artist C', deezer_id=503, source='deezer')
            db.session.add_all([second_song, first_song, missing_from_playlist])
            db.session.commit()
            first_song_id = first_song.id
            second_song_id = second_song.id

        import_calls = []

        def fake_import_item(**kwargs):
            import_calls.append(kwargs)
            return {
                'imported_count': 1,
                'skipped_count': 1,
                'error_count': 0,
                'errors': [],
                'song_ids': [first_song_id, second_song_id, 999999],
            }

        monkeypatch.setattr('musicround.routes.generate.ImportHelper.import_item', fake_import_item)
        _login(app, client)

        response = client.post(
            '/import-playlist',
            data={
                'platform': 'deezer',
                'playlist_url': 'https://www.deezer.com/playlist/playlist123?utm=test',
                'round_name': 'Deezer Regression',
            },
        )

        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert import_calls == [{
            'service_name': 'deezer',
            'item_type': 'playlist',
            'item_id': 'playlist123',
        }]
        assert body.index('First In Playlist') < body.index('Second In Database')
        assert 'Not In Playlist' not in body
        assert 'Deezer Playlist: playlist123' in body

    def test_spotify_playlist_import_preserves_imported_song_order(self, app, monkeypatch):
        """Spotify imported DB IDs should keep playlist order for review and export."""
        with app.app_context():
            app.config['SONGS_PER_ROUND'] = 3
            first_song = Song(title='First In Playlist', artist='Artist A', spotify_id='first')
            second_song = Song(title='Second In Playlist', artist='Artist B', spotify_id='second')
            third_song = Song(title='Third In Playlist', artist='Artist C', spotify_id='third')
            db.session.add_all([first_song, second_song, third_song])
            db.session.commit()
            ordered_ids = [third_song.id, first_song.id, second_song.id]

        def fake_import_item(**_kwargs):
            return {
                'imported_count': 3,
                'skipped_count': 0,
                'error_count': 0,
                'errors': [],
                'imported_song_ids': ordered_ids,
            }

        monkeypatch.setattr('musicround.routes.generate.ImportHelper.import_item', fake_import_item)
        monkeypatch.setattr('musicround.routes.generate.get_spotify_token', lambda: ('token', 'system'))
        monkeypatch.setattr('musicround.routes.generate.oauth', SimpleNamespace(spotify=object()))

        from musicround.routes.generate import get_songs_from_spotify_playlist
        with app.app_context():
            songs = get_songs_from_spotify_playlist('playlist123')

        assert [song.title for song in songs] == [
            'Third In Playlist',
            'First In Playlist',
            'Second In Playlist',
        ]

    def test_spotify_playlist_import_ignores_duplicate_and_invalid_song_ids(self, app, monkeypatch):
        """Spotify imported DB IDs should be sanitized without changing usable order."""
        with app.app_context():
            app.config['SONGS_PER_ROUND'] = 3
            first_song = Song(title='First In Playlist', artist='Artist A', spotify_id='first')
            second_song = Song(title='Second In Playlist', artist='Artist B', spotify_id='second')
            db.session.add_all([first_song, second_song])
            db.session.commit()
            returned_ids = [second_song.id, 'not-an-id', second_song.id, first_song.id, 999999]

        def fake_import_item(**_kwargs):
            return {
                'imported_count': 2,
                'skipped_count': 0,
                'error_count': 0,
                'errors': [],
                'imported_song_ids': returned_ids,
            }

        monkeypatch.setattr('musicround.routes.generate.ImportHelper.import_item', fake_import_item)
        monkeypatch.setattr('musicround.routes.generate.get_spotify_token', lambda: ('token', 'system'))
        monkeypatch.setattr('musicround.routes.generate.oauth', SimpleNamespace(spotify=object()))

        from musicround.routes.generate import get_songs_from_spotify_playlist
        with app.app_context():
            songs = get_songs_from_spotify_playlist('playlist123')

        assert [song.title for song in songs] == [
            'Second In Playlist',
            'First In Playlist',
        ]

    def test_import_spotify_playlist_rejects_partial_round(self, app, client, monkeypatch):
        """Playlist import should not offer a saveable review if too few tracks resolve."""
        with app.app_context():
            app.config['SONGS_PER_ROUND'] = 2
            resolved = Song(title='Only Resolved', artist='Artist A', spotify_id='one')
            db.session.add(resolved)
            db.session.commit()
            resolved_id = resolved.id

        def fake_get_songs_from_spotify_playlist(_playlist_id):
            return [Song.query.get(resolved_id)]

        monkeypatch.setattr(
            'musicround.routes.generate.get_songs_from_spotify_playlist',
            fake_get_songs_from_spotify_playlist,
        )
        _login(app, client)

        response = client.post(
            '/import-playlist',
            data={
                'platform': 'spotify',
                'playlist_url': 'https://open.spotify.com/playlist/partial',
                'round_name': 'Partial Spotify',
            },
            follow_redirects=True,
        )

        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert 'resolved 1 songs; expected exactly 2' in body
        assert 'Only Resolved' not in body
        with app.app_context():
            assert Round.query.filter_by(name='Partial Spotify').first() is None
