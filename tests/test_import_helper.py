"""Tests for unified import helper behavior."""
from musicround.helpers.import_helper import ImportHelper


class DeezerPlaylistStub:
    """Minimal Deezer client stub for playlist import result contracts."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def import_playlist(self, playlist_id, lastfm_api_key=None):
        self.calls.append((playlist_id, lastfm_api_key))
        return self.result


class TestImportHelperDeezer:
    """Tests for Deezer import result handling."""

    def test_deezer_playlist_uses_reported_import_and_skip_counts(self, app):
        """Playlist imports must report DeezerClient's actual counters."""
        result = {
            'imported_songs': ['song-a', 'song-b'],
            'skipped_songs': ['duplicate-a'],
            'imported_count': 2,
            'skipped_count': 1,
            'song_ids': [10, 11, 12],
        }
        deezer = DeezerPlaylistStub(result)

        with app.app_context():
            app.config['deezer'] = deezer
            app.config['LASTFM_API_KEY'] = 'lastfm-test-key'

            response = ImportHelper.import_item('deezer', 'playlist', 'playlist-123')

        assert response == {
            'imported_count': 2,
            'skipped_count': 1,
            'error_count': 0,
            'errors': [],
            'song_ids': [10, 11, 12],
        }
        assert deezer.calls == [('playlist-123', 'lastfm-test-key')]

    def test_deezer_playlist_empty_counts_return_error(self, app):
        """An empty Deezer playlist result should be treated as no songs found."""
        deezer = DeezerPlaylistStub({
            'imported_songs': [],
            'skipped_songs': [],
            'imported_count': 0,
            'skipped_count': 0,
        })

        with app.app_context():
            app.config['deezer'] = deezer

            response = ImportHelper.import_item('deezer', 'playlist', 'playlist-empty')

        assert response['imported_count'] == 0
        assert response['skipped_count'] == 0
        assert response['error_count'] == 1
        assert 'No songs found in Deezer playlist playlist-empty' in response['errors'][0]
