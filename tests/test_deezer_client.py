"""Tests for the Deezer API client."""
import pytest
from unittest.mock import patch, MagicMock
from musicround.deezer_client import DeezerClient


class MockResponse:
    """Helper mock for requests.Response."""

    def __init__(self, json_data=None, status_code=200, raise_for_status=False):
        self._json_data = json_data or {}
        self.status_code = status_code
        self._raise = raise_for_status

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self._raise:
            import requests
            raise requests.HTTPError(response=self)


class TestDeezerClientInit:
    """Tests for DeezerClient initialisation."""

    def test_client_creation(self):
        """Test that DeezerClient can be created."""
        client = DeezerClient()
        assert client is not None
        assert client.base_url == 'https://api.deezer.com'

    def test_client_has_logger(self):
        """Test that DeezerClient has a logger."""
        client = DeezerClient()
        assert client.logger is not None


class TestMakeRequest:
    """Tests for DeezerClient._make_request."""

    @patch('musicround.deezer_client.requests.get')
    def test_successful_request(self, mock_get):
        """Test a successful API request returns parsed JSON."""
        mock_get.return_value = MockResponse({'id': 1, 'title': 'Hello'})
        client = DeezerClient()
        result = client._make_request('track/1')
        assert result == {'id': 1, 'title': 'Hello'}
        mock_get.assert_called_once()

    @patch('musicround.deezer_client.requests.get')
    def test_request_error_returns_none(self, mock_get):
        """Test that a request exception returns None."""
        import requests
        mock_get.side_effect = requests.RequestException('Network error')
        client = DeezerClient()
        result = client._make_request('track/1')
        assert result is None

    @patch('musicround.deezer_client.requests.get')
    def test_request_builds_correct_url(self, mock_get):
        """Test that the correct URL is constructed."""
        mock_get.return_value = MockResponse({'data': []})
        client = DeezerClient()
        client._make_request('search/track', params={'q': 'rock'})
        call_args = mock_get.call_args
        assert call_args[0][0] == 'https://api.deezer.com/search/track'
        assert call_args[1]['params'] == {'q': 'rock'}


class TestSearchMethods:
    """Tests for DeezerClient search methods."""

    @patch('musicround.deezer_client.requests.get')
    def test_search_tracks_returns_items(self, mock_get):
        """Test search_tracks returns track list."""
        mock_get.return_value = MockResponse({
            'data': [
                {'id': 1, 'title': 'Song 1'},
                {'id': 2, 'title': 'Song 2'},
            ]
        })
        client = DeezerClient()
        results = client.search_tracks('rock')
        assert len(results) == 2
        assert results[0]['title'] == 'Song 1'

    @patch('musicround.deezer_client.requests.get')
    def test_search_tracks_empty_when_no_data(self, mock_get):
        """Test search_tracks returns empty list when no data key."""
        mock_get.return_value = MockResponse({'error': 'no results'})
        client = DeezerClient()
        results = client.search_tracks('nonexistent')
        assert results == []

    @patch('musicround.deezer_client.requests.get')
    def test_search_tracks_empty_when_none(self, mock_get):
        """Test search_tracks returns empty list when request fails."""
        import requests
        mock_get.side_effect = requests.RequestException('error')
        client = DeezerClient()
        results = client.search_tracks('query')
        assert results == []

    @patch('musicround.deezer_client.requests.get')
    def test_search_albums_returns_items(self, mock_get):
        """Test search_albums returns album list."""
        mock_get.return_value = MockResponse({
            'data': [{'id': 10, 'title': 'Album A'}]
        })
        client = DeezerClient()
        results = client.search_albums('beatles')
        assert len(results) == 1
        assert results[0]['title'] == 'Album A'

    @patch('musicround.deezer_client.requests.get')
    def test_search_albums_empty_when_no_data(self, mock_get):
        """Test search_albums returns empty list when response has no data."""
        mock_get.return_value = MockResponse({})
        client = DeezerClient()
        results = client.search_albums('nothing')
        assert results == []

    @patch('musicround.deezer_client.requests.get')
    def test_search_playlists_returns_items(self, mock_get):
        """Test search_playlists returns playlist list."""
        mock_get.return_value = MockResponse({
            'data': [
                {'id': 100, 'title': 'Top Hits'},
                {'id': 101, 'title': 'Chill Vibes'},
            ]
        })
        client = DeezerClient()
        results = client.search_playlists('hits')
        assert len(results) == 2

    @patch('musicround.deezer_client.requests.get')
    def test_search_playlists_empty_when_no_data(self, mock_get):
        """Test search_playlists returns empty list when response has no data."""
        mock_get.return_value = MockResponse({'total': 0})
        client = DeezerClient()
        results = client.search_playlists('nothing')
        assert results == []


class TestGetMethods:
    """Tests for DeezerClient get_* methods."""

    @patch('musicround.deezer_client.requests.get')
    def test_get_track(self, mock_get):
        """Test get_track returns track details."""
        track_data = {'id': 42, 'title': 'Track Title', 'artist': {'name': 'Artist'}}
        mock_get.return_value = MockResponse(track_data)
        client = DeezerClient()
        result = client.get_track(42)
        assert result == track_data

    @patch('musicround.deezer_client.requests.get')
    def test_get_track_error(self, mock_get):
        """Test get_track returns None on error."""
        import requests
        mock_get.side_effect = requests.RequestException()
        client = DeezerClient()
        result = client.get_track(99)
        assert result is None

    @patch('musicround.deezer_client.requests.get')
    def test_get_album(self, mock_get):
        """Test get_album returns album details."""
        album_data = {'id': 55, 'title': 'Some Album', 'tracks': {'data': []}}
        mock_get.return_value = MockResponse(album_data)
        client = DeezerClient()
        result = client.get_album(55)
        assert result == album_data

    @patch('musicround.deezer_client.requests.get')
    def test_get_album_tracks(self, mock_get):
        """Test get_album_tracks returns track list."""
        mock_get.return_value = MockResponse({
            'data': [{'id': 1, 'title': 'Track 1'}, {'id': 2, 'title': 'Track 2'}]
        })
        client = DeezerClient()
        results = client.get_album_tracks(55)
        assert len(results) == 2

    @patch('musicround.deezer_client.requests.get')
    def test_get_album_tracks_empty(self, mock_get):
        """Test get_album_tracks returns empty list on missing data key."""
        mock_get.return_value = MockResponse({})
        client = DeezerClient()
        results = client.get_album_tracks(55)
        assert results == []

    @patch('musicround.deezer_client.requests.get')
    def test_get_playlist(self, mock_get):
        """Test get_playlist returns playlist details."""
        playlist_data = {'id': 77, 'title': 'My Playlist', 'nb_tracks': 10}
        mock_get.return_value = MockResponse(playlist_data)
        client = DeezerClient()
        result = client.get_playlist(77)
        assert result == playlist_data

    @patch('musicround.deezer_client.requests.get')
    def test_get_playlist_tracks(self, mock_get):
        """Test get_playlist_tracks returns track list."""
        mock_get.return_value = MockResponse({
            'data': [{'id': 1, 'title': 'PT 1'}, {'id': 2, 'title': 'PT 2'}]
        })
        client = DeezerClient()
        results = client.get_playlist_tracks(77)
        assert len(results) == 2

    @patch('musicround.deezer_client.requests.get')
    def test_get_playlist_tracks_empty(self, mock_get):
        """Test get_playlist_tracks returns empty list on missing data key."""
        mock_get.return_value = MockResponse({'total': 0})
        client = DeezerClient()
        results = client.get_playlist_tracks(77)
        assert results == []

    @patch('musicround.deezer_client.requests.get')
    def test_get_playlist_tracks_error(self, mock_get):
        """Test get_playlist_tracks returns empty list on request failure."""
        import requests
        mock_get.side_effect = requests.RequestException()
        client = DeezerClient()
        results = client.get_playlist_tracks(99)
        assert results == []
