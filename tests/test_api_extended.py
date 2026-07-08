"""Extended API endpoint tests."""
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests

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


def _make_response(status_code, json_body=None, text=''):
    response = MagicMock()
    response.status_code = status_code
    response.text = text or str(json_body)
    if json_body is None:
        response.json.side_effect = ValueError('no json')
    else:
        response.json.return_value = json_body
    return response


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

    def test_create_tag_requires_login(self, app, client):
        """Test POST /api/tags requires authentication."""
        response = client.post(
            '/api/tags',
            data=json.dumps({'name': 'AnonymousTag'}),
            content_type='application/json',
        )
        assert response.status_code in (302, 401, 403)

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

    def test_add_tag_to_song_requires_login(self, app, client):
        """Test POST /api/songs/<id>/tags requires authentication."""
        song_id = _create_song(app, 'AnonymousTagSong', 'Artist')
        response = client.post(
            f'/api/songs/{song_id}/tags',
            data=json.dumps({'tag_name': 'ShouldNotApply'}),
            content_type='application/json',
        )
        assert response.status_code in (302, 401, 403)

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

    def test_remove_tag_from_song_requires_login(self, app, client):
        """Test DELETE /api/songs/<id>/tags/<tag_id> requires authentication."""
        with app.app_context():
            tag = Tag(name='AnonymousRemoveTag')
            song = Song(title='AnonymousRemoveSong', artist='A', genre='Pop')
            db.session.add_all([tag, song])
            db.session.commit()
            song.tags.append(tag)
            db.session.commit()
            song_id = song.id
            tag_id = tag.id

        response = client.delete(f'/api/songs/{song_id}/tags/{tag_id}')
        assert response.status_code in (302, 401, 403)

    def test_refresh_metadata_requires_login(self, app, client):
        """Test POST /api/songs/<id>/refresh-metadata requires authentication."""
        song_id = _create_song(app, 'AnonymousRefreshSong', 'Artist')
        response = client.post(f'/api/songs/{song_id}/refresh-metadata')
        assert response.status_code in (302, 401, 403)

    def test_refresh_metadata_unexpected_error_hides_exception_text(self, app, client):
        """Metadata provider failures should not leak exception text to clients."""
        _create_user_and_login(app, client, 'metafail', 'metafail@example.com')
        with app.app_context():
            song = Song(title='Meta Fail', artist='Artist', genre='Rock', isrc='USMETA123456')
            db.session.add(song)
            db.session.commit()
            song_id = song.id

        with patch(
            'musicround.routes.api.get_song_metadata_by_isrc',
            side_effect=RuntimeError('provider-secret metadata traceback'),
        ):
            response = client.post(f'/api/songs/{song_id}/refresh-metadata')

        data = response.get_json()
        assert response.status_code == 500
        assert data == {
            'error': 'Unable to refresh song metadata.',
            'code': 'metadata_refresh_failed',
        }
        assert 'provider-secret' not in response.get_data(as_text=True)
        assert 'traceback' not in data

    def test_refresh_metadata_db_error_hides_exception_text(self, app, client):
        """Metadata save failures should stay generic client-side."""
        _create_user_and_login(app, client, 'metadbfail', 'metadbfail@example.com')
        with app.app_context():
            song = Song(title='Meta DB Fail', artist='Artist', genre='Rock', isrc='USMETA654321')
            db.session.add(song)
            db.session.commit()
            song_id = song.id

        with patch(
            'musicround.routes.api.get_song_metadata_by_isrc',
            return_value={'title': 'Updated Title', 'sources': ['test']},
        ), patch(
            'musicround.routes.api.db.session.commit',
            side_effect=RuntimeError('database-secret /data/song_data.db'),
        ):
            response = client.post(f'/api/songs/{song_id}/refresh-metadata')

        data = response.get_json()
        assert response.status_code == 500
        assert data == {
            'error': 'Unable to save refreshed song metadata.',
            'code': 'metadata_refresh_save_failed',
        }
        assert 'database-secret' not in response.get_data(as_text=True)
        assert '/data/song_data.db' not in response.get_data(as_text=True)


class TestSongSearchApi:
    """Tests for /api/songs/search endpoint."""

    def test_list_songs_filters_and_paginates(self, app, client):
        """Test catalog listing applies server-side filters and pagination."""
        _create_user_and_login(app, client, 'listfilter', 'listfilter@example.com')
        with app.app_context():
            songs = [
                Song(
                    title='Filtered Rock 1999',
                    artist='Alpha',
                    genre='Rock',
                    year=1999,
                    preview_url='https://example.test/alpha.mp3',
                    used_count=0,
                ),
                Song(
                    title='Filtered Pop 2005',
                    artist='Beta',
                    genre='Pop',
                    year=2005,
                    used_count=3,
                ),
                Song(
                    title='Other Rock 2010',
                    artist='Gamma',
                    genre='Rock',
                    year=2010,
                    deezer_preview_url='https://example.test/gamma.mp3',
                ),
            ]
            db.session.add_all(songs)
            db.session.commit()

        response = client.get(
            '/api/songs?q=Filtered&genre=Rock&year_min=1990&year_max=2000'
            '&has_preview=true&unused_only=true&per_page=5'
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'success'
        assert data['pagination']['total'] == 1
        assert data['pagination']['page'] == 1
        assert data['pagination']['per_page'] == 5
        assert data['data'][0]['title'] == 'Filtered Rock 1999'
        assert data['data'][0]['preview_url'] == 'https://example.test/alpha.mp3'

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

    def test_search_songs_supports_catalog_filters(self, app, client):
        """Test legacy search endpoint can use the shared catalog filters."""
        _create_user_and_login(app, client, 'searchfilters', 'searchfilters@example.com')
        with app.app_context():
            tag = Tag(name='summer')
            songs = [
                Song(
                    title='Filtered Rock Legacy',
                    artist='Rock Band',
                    genre='Rock',
                    tempo=118.0,
                    preview_url='https://example.test/legacy.mp3',
                ),
                Song(title='Filtered Pop Legacy', artist='Pop Band', genre='Pop'),
            ]
            songs[0].tags.append(tag)
            db.session.add_all(songs)
            db.session.commit()

        response = client.get(
            '/api/songs/search?q=Filtered&genre=Rock&tag=summer'
            '&tempo_min=100&tempo_max=130&has_preview=true'
        )
        assert response.status_code == 200
        data = response.get_json()
        assert [song['title'] for song in data] == ['Filtered Rock Legacy']
        assert data[0]['search_score'] > 0
        assert data[0]['match_reasons']

    def test_search_songs_returns_platform_preview_fallback(self, app, client):
        """Test compact song payload exposes any available platform preview."""
        _create_user_and_login(app, client, 'previewfallback', 'previewfallback@example.com')
        with app.app_context():
            song = Song(
                title='Fallback Preview Song',
                artist='Preview Artist',
                genre='Rock',
                deezer_preview_url='https://example.test/deezer.mp3',
            )
            db.session.add(song)
            db.session.commit()

        response = client.get('/api/songs/search?q=Fallback&has_preview=true')
        assert response.status_code == 200
        data = response.get_json()
        assert data[0]['preview_url'] == 'https://example.test/deezer.mp3'

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


class TestSpotifyApiErrors:
    """Spotify proxy endpoints should not expose provider error bodies."""

    def _spotify_http_error(self):
        response = MagicMock()
        response.status_code = 401
        response.text = 'provider-secret spotify-access-token traceback'
        response.content = response.text.encode('utf-8')
        response.json.return_value = {
            'error': {
                'message': 'provider-secret spotify-access-token traceback',
            }
        }
        return requests.exceptions.HTTPError(response=response)

    def test_spotify_album_error_hides_provider_body(self, app, client):
        _create_user_and_login(app, client, 'spotifyalbumerr', 'spotifyalbumerr@example.com')
        fake_response = MagicMock()
        fake_response.raise_for_status.side_effect = self._spotify_http_error()

        with patch('musicround.routes.api.get_spotify_token', return_value=('spotify-token', 'manual')), \
                patch('musicround.routes.api.requests.get', return_value=fake_response):
            response = client.get('/api/spotify/album/album-id')

        data = response.get_json()
        assert response.status_code == 401
        assert data == {
            'error': 'Spotify API error',
            'code': 'spotify_api_error',
            'status_code': 401,
        }
        assert 'provider-secret' not in response.get_data(as_text=True)
        assert 'spotify-access-token' not in response.get_data(as_text=True)
        assert 'details' not in data

    def test_spotify_playlist_error_hides_provider_body(self, app, client):
        _create_user_and_login(app, client, 'spotifyplaylisterr', 'spotifyplaylisterr@example.com')
        fake_response = MagicMock()
        fake_response.raise_for_status.side_effect = self._spotify_http_error()

        with patch('musicround.routes.api.get_spotify_token', return_value=('spotify-token', 'manual')), \
                patch('musicround.routes.api.requests.get', return_value=fake_response):
            response = client.get('/api/spotify/playlist/playlist-id')

        data = response.get_json()
        assert response.status_code == 401
        assert data['code'] == 'spotify_api_error'
        assert 'provider-secret' not in response.get_data(as_text=True)
        assert 'details' not in data

    def test_spotify_search_error_hides_provider_body(self, app, client):
        _create_user_and_login(app, client, 'spotifysearcherr', 'spotifysearcherr@example.com')
        fake_response = MagicMock()
        fake_response.raise_for_status.side_effect = self._spotify_http_error()

        with patch('musicround.routes.api.get_spotify_token', return_value=('spotify-token', 'manual')), \
                patch('musicround.routes.api.requests.get', return_value=fake_response):
            response = client.get('/api/spotify/search?q=beatles&type=track')

        data = response.get_json()
        assert response.status_code == 401
        assert data['code'] == 'spotify_api_error'
        assert 'provider-secret' not in response.get_data(as_text=True)
        assert 'details' not in data


class TestDropboxFolderApi:
    """Tests for Dropbox folder browser API error recovery."""

    def _login_dropbox_user(self, app, client):
        _create_user_and_login(app, client, 'dropboxapi', 'dropboxapi@example.com')
        with app.app_context():
            user = User.query.filter_by(username='dropboxapi').one()
            user.dropbox_id = 'dropbox-account'
            user.dropbox_token = 'old-dropbox-access'
            user.dropbox_refresh_token = 'old-dropbox-refresh'
            user.dropbox_token_expiry = datetime.now() + timedelta(hours=1)
            db.session.commit()

    def test_list_folders_refreshes_and_retries_after_401(self, app, client):
        """Folder listing should retry once with a force-refreshed Dropbox token."""
        self._login_dropbox_user(app, client)

        def fake_refresh(user, force=False):
            assert force is True
            user.dropbox_token = 'new-dropbox-access'
            db.session.commit()
            return {'success': True, 'message': 'Token refreshed'}

        with patch('musicround.routes.api.requests.post') as mock_post, \
                patch(
                    'musicround.helpers.dropbox_helper.refresh_dropbox_token_if_needed',
                    side_effect=fake_refresh,
                ):
            mock_post.side_effect = [
                _make_response(401, {'error_summary': 'expired_access_token/'}),
                _make_response(200, {'entries': [{'.tag': 'folder', 'name': 'Rounds', 'path_display': '/Rounds', 'id': 'id:1'}]}),
            ]

            response = client.get('/api/dropbox/folders')

        data = response.get_json()
        assert response.status_code == 200
        assert data['folders'][0]['name'] == 'Rounds'
        from musicround.helpers.dropbox_helper import DROPBOX_API_TIMEOUT_SECONDS
        assert mock_post.call_args_list[0].kwargs['timeout'] == DROPBOX_API_TIMEOUT_SECONDS
        assert mock_post.call_args_list[1].kwargs['timeout'] == DROPBOX_API_TIMEOUT_SECONDS
        assert mock_post.call_args_list[1].kwargs['headers']['Authorization'] == (
            'Bearer new-dropbox-access'
        )

    def test_list_folders_returns_reconnect_required_after_revoked_refresh(self, app, client):
        """Folder listing should surface an actionable reconnect payload."""
        self._login_dropbox_user(app, client)

        with patch('musicround.routes.api.requests.post') as mock_post, \
                patch(
                    'musicround.helpers.dropbox_helper.refresh_dropbox_token_if_needed',
                    return_value={
                        'success': False,
                        'message': 'Dropbox connection expired. Please reconnect Dropbox.',
                        'reconnect_required': True,
                    },
                ):
            mock_post.return_value = _make_response(401, {'error_summary': 'expired_access_token/'})

            response = client.get('/api/dropbox/folders')

        data = response.get_json()
        assert response.status_code == 401
        assert data['reconnect_required'] is True
        assert 'reconnect Dropbox' in data['error']

    def test_list_folders_non_json_dropbox_error_hides_raw_provider_body(self, app, client):
        """Non-JSON Dropbox errors should not expose provider bodies to the browser."""
        self._login_dropbox_user(app, client)

        with patch('musicround.routes.api.requests.post') as mock_post:
            mock_post.return_value = _make_response(
                503,
                json_body=None,
                text='provider-secret-body old-dropbox-access traceback',
            )

            response = client.get('/api/dropbox/folders')

        data = response.get_json()
        assert response.status_code == 502
        from musicround.helpers.dropbox_helper import DROPBOX_API_TIMEOUT_SECONDS
        assert mock_post.call_args.kwargs['timeout'] == DROPBOX_API_TIMEOUT_SECONDS
        assert data['code'] == 'dropbox_api_error'
        assert data['status_code'] == 503
        assert 'raw_response' not in data
        assert 'traceback' not in data
        assert 'provider-secret-body' not in response.get_data(as_text=True)

    def test_list_folders_json_dropbox_error_hides_provider_details(self, app, client):
        """JSON Dropbox errors should not be returned as raw details."""
        self._login_dropbox_user(app, client)

        with patch('musicround.routes.api.requests.post') as mock_post:
            mock_post.return_value = _make_response(
                403,
                {
                    'error_summary': 'provider-json-secret old-dropbox-access traceback',
                    'error': {'reason': 'provider-json-secret'},
                },
            )

            response = client.get('/api/dropbox/folders')

        data = response.get_json()
        assert response.status_code == 403
        from musicround.helpers.dropbox_helper import DROPBOX_API_TIMEOUT_SECONDS
        assert mock_post.call_args.kwargs['timeout'] == DROPBOX_API_TIMEOUT_SECONDS
        assert data['code'] == 'dropbox_api_error'
        assert data['status_code'] == 403
        assert 'details' not in data
        assert 'provider-json-secret' not in response.get_data(as_text=True)
        assert 'old-dropbox-access' not in response.get_data(as_text=True)

    def test_list_folders_unexpected_error_hides_traceback(self, app, client):
        """Unexpected Dropbox folder errors should stay generic client-side."""
        self._login_dropbox_user(app, client)

        with patch('musicround.routes.api.requests.post', side_effect=RuntimeError('secret failure')):
            response = client.get('/api/dropbox/folders')

        data = response.get_json()
        assert response.status_code == 500
        assert data['code'] == 'dropbox_folder_list_failed'
        assert 'traceback' not in data
        assert 'secret failure' not in response.get_data(as_text=True)

    def test_create_folder_non_json_dropbox_error_hides_raw_provider_body(self, app, client):
        """Create-folder Dropbox errors should not expose raw provider bodies."""
        self._login_dropbox_user(app, client)

        with patch('musicround.routes.api.requests.post') as mock_post:
            mock_post.return_value = _make_response(
                502,
                json_body=None,
                text='provider-create-secret old-dropbox-access traceback',
            )

            response = client.post(
                '/api/dropbox/create-folder',
                data=json.dumps({'parent_path': '/', 'folder_name': 'Rounds'}),
                content_type='application/json',
            )

        data = response.get_json()
        assert response.status_code == 502
        from musicround.helpers.dropbox_helper import DROPBOX_API_TIMEOUT_SECONDS
        assert mock_post.call_args.kwargs['timeout'] == DROPBOX_API_TIMEOUT_SECONDS
        assert data['code'] == 'dropbox_api_error'
        assert data['status_code'] == 502
        assert 'raw_response' not in data
        assert 'traceback' not in data
        assert 'provider-create-secret' not in response.get_data(as_text=True)

    def test_create_folder_json_dropbox_error_hides_provider_details(self, app, client):
        """Create-folder JSON errors should not expose raw provider details."""
        self._login_dropbox_user(app, client)

        with patch('musicround.routes.api.requests.post') as mock_post:
            mock_post.return_value = _make_response(
                403,
                {
                    'error_summary': 'provider-create-json-secret old-dropbox-access traceback',
                    'error': {'reason': 'provider-create-json-secret'},
                },
            )

            response = client.post(
                '/api/dropbox/create-folder',
                data=json.dumps({'parent_path': '/', 'folder_name': 'Rounds'}),
                content_type='application/json',
            )

        data = response.get_json()
        assert response.status_code == 403
        assert data['code'] == 'dropbox_api_error'
        assert data['status_code'] == 403
        assert 'details' not in data
        assert 'provider-create-json-secret' not in response.get_data(as_text=True)
        assert 'old-dropbox-access' not in response.get_data(as_text=True)

    def test_create_folder_conflict_hides_provider_details(self, app, client):
        """Folder-exists responses should be useful without leaking Dropbox bodies."""
        self._login_dropbox_user(app, client)

        with patch('musicround.routes.api.requests.post') as mock_post:
            mock_post.return_value = _make_response(
                409,
                {
                    'error_summary': 'path/conflict/folder/ provider-conflict-secret',
                    'error': {'reason': 'provider-conflict-secret'},
                },
                text='path/conflict/folder/ provider-conflict-secret',
            )

            response = client.post(
                '/api/dropbox/create-folder',
                data=json.dumps({'parent_path': '/', 'folder_name': 'Rounds'}),
                content_type='application/json',
            )

        data = response.get_json()
        assert response.status_code == 409
        from musicround.helpers.dropbox_helper import DROPBOX_API_TIMEOUT_SECONDS
        assert mock_post.call_args.kwargs['timeout'] == DROPBOX_API_TIMEOUT_SECONDS
        assert data['code'] == 'dropbox_folder_exists'
        assert data['status_code'] == 409
        assert 'details' not in data
        assert 'provider-conflict-secret' not in response.get_data(as_text=True)

    def test_root_folder_fallback_hides_raw_provider_body(self, app):
        """Root-folder fallback should not expose Dropbox provider bodies."""
        from musicround.routes.api import list_root_folders

        with app.test_request_context('/api/dropbox/folders?path=/Missing'):
            with patch('musicround.routes.api.requests.post') as mock_post:
                mock_post.return_value = _make_response(
                    503,
                    json_body=None,
                    text='provider-root-secret old-dropbox-access traceback',
                )

                response, status = list_root_folders('old-dropbox-access', attempted_path='/Missing')

        data = response.get_json()
        assert status == 503
        from musicround.helpers.dropbox_helper import DROPBOX_API_TIMEOUT_SECONDS
        assert mock_post.call_args.kwargs['timeout'] == DROPBOX_API_TIMEOUT_SECONDS
        assert data['code'] == 'dropbox_api_error'
        assert data['status_code'] == 503
        assert data['attempted_path'] == '/Missing'
        assert 'provider-root-secret' not in response.get_data(as_text=True)
        assert 'traceback' not in data

    def test_root_folder_fallback_unexpected_error_hides_exception(self, app):
        """Unexpected root-folder fallback failures should remain generic."""
        from musicround.routes.api import list_root_folders

        with app.test_request_context('/api/dropbox/folders?path=/Missing'):
            with patch(
                'musicround.routes.api.requests.post',
                side_effect=RuntimeError('provider-root-secret old-dropbox-access'),
            ):
                response, status = list_root_folders('old-dropbox-access', attempted_path='/Missing')

        data = response.get_json()
        assert status == 500
        assert data['code'] == 'dropbox_root_folder_list_failed'
        assert data['attempted_path'] == '/Missing'
        assert 'provider-root-secret' not in response.get_data(as_text=True)
        assert 'old-dropbox-access' not in response.get_data(as_text=True)
