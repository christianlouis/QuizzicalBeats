import unittest
import sys
import os
import logging
import dotenv
from unittest.mock import patch, MagicMock

# Add the project root to Python path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Create the helpers directory if it doesn't exist
helpers_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'musicround', 'helpers')
if not os.path.exists(helpers_dir):
    os.makedirs(helpers_dir)

# Create __init__.py if it doesn't exist
helpers_init = os.path.join(helpers_dir, '__init__.py')
if not os.path.exists(helpers_init):
    with open(helpers_init, 'w') as f:
        f.write('# This file makes the helpers directory a proper Python package\n')

from musicround.helpers.metadata import (
    get_song_metadata_by_isrc,
    get_musicbrainz_data,
    get_spotify_data,
    get_deezer_data,
    get_lastfm_data,
    get_openai_data,
    get_acrcloud_data
)

class TestMetadataHelper(unittest.TestCase):
    """Tests for the metadata helper functions."""
    
    def setUp(self):
        """Set up common test resources."""
        # Create a mock Flask app with logger
        self.mock_app = MagicMock()
        self.mock_app.logger = logging.getLogger("test_logger")
        self.mock_app.config = {}
        
        # Test ISRC for AC/DC's Highway to Hell
        self.test_isrc = "AUAP07900028"

    @patch('musicround.helpers.metadata.get_musicbrainz_data')
    @patch('musicround.helpers.metadata.get_spotify_data')
    @patch('musicround.helpers.metadata.get_deezer_data')
    @patch('musicround.helpers.metadata.get_lastfm_data')
    @patch('musicround.helpers.metadata.get_openai_data')
    @patch('musicround.helpers.metadata.get_acrcloud_data')  # Add the new mock for ACRCloud
    def test_acdc_highway_to_hell(self, mock_acrcloud, mock_openai, mock_lastfm, mock_deezer, 
                                  mock_spotify, mock_musicbrainz):
        """Test that AC/DC's Highway to Hell returns correct metadata."""
        # Set up mock return values
        mock_musicbrainz.return_value = {
            "title": "Highway to Hell",
            "artist_name": "AC/DC",
            "year": "1979",
            "genre": "Hard Rock"
        }
        
        mock_spotify.return_value = {
            "title": "Highway to Hell",
            "artist_name": "AC/DC",
            "year": "1979",
            "genre": "Hard Rock",
            "popularity": 82
        }
        
        mock_deezer.return_value = {
            "title": "Highway to Hell",
            "artist_name": "AC/DC",
            "year": "1979",
            "preview_url": "https://cdns-preview-8.dzcdn.net/stream/c-8f5a9d479bc54be17e2754cb9653e60b-6.mp3"
        }
        
        mock_lastfm.return_value = {
            "genre": "Classic Rock"
        }
        
        mock_openai.return_value = {
            "genre": "Rock",
            "year": "1979"
        }
        
        # Add ACRCloud mock data
        mock_acrcloud.return_value = {
            "title": "Highway to Hell",
            "artist_name": "AC/DC",
            "year": "1979",
            "genre": ["Rock", "Hard Rock"],
            "spotify_id": "2zYzyRzz6pRmhPzyfMEC8s",
            "deezer_id": "89077521",
            "preview_url": "https://audio-ssl.spotify.com/preview/track1234.mp3"
        }
        
        # Call function with test ISRC
        metadata = get_song_metadata_by_isrc(self.test_isrc, self.mock_app)
        
        # Verify mock functions were called correctly
        mock_acrcloud.assert_called_once_with(self.test_isrc, self.mock_app)
        mock_musicbrainz.assert_called_once_with(self.test_isrc, self.mock_app.logger)
        mock_spotify.assert_called_once_with(self.test_isrc, self.mock_app)
        mock_deezer.assert_called_once_with(self.test_isrc, self.mock_app)
        
        # LastFM and OpenAI should be called with title and artist name
        mock_lastfm.assert_called_once_with("AC/DC", "Highway to Hell", self.mock_app)
        mock_openai.assert_called_once_with("AC/DC", "Highway to Hell", self.mock_app)
        
        # Assert the expected metadata values
        self.assertEqual(metadata["title"], "Highway to Hell")
        self.assertEqual(metadata["artist_name"], "AC/DC")
        self.assertEqual(metadata["year"], "1979")
        
        # Genre should be the most common one from all sources
        self.assertEqual(metadata["genre"], "Hard Rock")  # Hard Rock appears most frequently in our mocks
        
        self.assertEqual(metadata["popularity"], 82)
        # Preview URL should be from Spotify since we prioritize it
        self.assertEqual(metadata["preview_url"], 
                         "https://audio-ssl.spotify.com/preview/track1234.mp3")
        
        # Check that ACRCloud platform IDs are present
        self.assertEqual(metadata["spotify_id"], "2zYzyRzz6pRmhPzyfMEC8s")
        self.assertEqual(metadata["deezer_id"], "89077521")
        
        # Check that all sources are included
        expected_sources = ["acrcloud", "musicbrainz", "spotify", "deezer", "lastfm", "openai"]
        self.assertCountEqual(metadata["sources"], expected_sources)
        
    @patch('musicround.helpers.metadata.requests.get')
    @patch('musicround.helpers.metadata.musicbrainzngs.search_recordings')
    def test_integration_with_real_data(self, mock_mb_search, mock_requests):
        """
        Test with more realistic data structures that might be returned by APIs.
        This is still a mock test but with more complex structures.
        """
        # Set up MockResponse class for requests
        class MockResponse:
            def __init__(self, json_data, status_code):
                self.json_data = json_data
                self.status_code = status_code
                
            def json(self):
                return self.json_data
        
        # Mock MusicBrainz data
        mock_mb_search.return_value = {
            'recording-list': [{
                'title': 'Highway to Hell',
                'artist-credit': [
                    {'artist': {'name': 'AC/DC'}}
                ],
                'tag-list': [
                    {'name': 'hard rock'},
                    {'name': 'rock'},
                    {'name': 'classic rock'}
                ],
                'release-list': [
                    {'date': '1979-07-27'}
                ]
            }]
        }
        
        # Mock Last.fm response
        mock_lastfm_response = {
            'track': {
                'name': 'Highway to Hell',
                'artist': {'name': 'AC/DC'},
                'toptags': {
                    'tag': [
                        {'name': 'rock'},
                        {'name': 'classic rock'},
                        {'name': 'hard rock'}
                    ]
                }
            }
        }
        
        # Set up the mock for requests.get to return the mock response
        def mock_request_get(url, **kwargs):
            if 'audioscrobbler.com' in url:
                return MockResponse(mock_lastfm_response, 200)
            return MockResponse({}, 404)
            
        mock_requests.side_effect = mock_request_get
        
        # Since we can't easily mock everything, we'll patch the other functions
        with patch('musicround.helpers.metadata.get_spotify_data') as mock_spotify, \
             patch('musicround.helpers.metadata.get_deezer_data') as mock_deezer, \
             patch('musicround.helpers.metadata.get_openai_data') as mock_openai:
            
            mock_spotify.return_value = {}
            mock_deezer.return_value = {}
            mock_openai.return_value = {}
            
            # Only test MusicBrainz data in this test
            metadata = get_song_metadata_by_isrc(self.test_isrc, self.mock_app)
            
            # Verify the results
            self.assertEqual(metadata["title"], "Highway to Hell")
            self.assertEqual(metadata["artist_name"], "AC/DC")
            self.assertEqual(metadata["year"], "1979")
            self.assertEqual(metadata["genre"], "hard rock")  # First tag from tag-list

    def test_real_api_calls(self):
        """
        Test actual API calls with AC/DC's Highway to Hell.
        This test makes real API calls so it should be skipped by default.
        Run this test manually when needed by removing the skip decorator.
        """
        # Load environment variables from .env file
        dotenv.load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))
        
        # Initialize test app with valid API keys
        real_app = MagicMock()
        real_app.logger = logging.getLogger("real_api_test")
        real_app.logger.setLevel(logging.INFO)
        
        # Add a console handler to see the logs
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        real_app.logger.addHandler(console_handler)
        
        # Set up config with actual API keys from .env file
        real_app.config = {
            'LASTFM_API_KEY': os.environ.get('LASTFM_API_KEY'),
            'OPENAI_API_KEY': os.environ.get('OPENAI_API_KEY'),
            'OPENAI_MODEL': os.environ.get('OPENAI_MODEL', 'gpt-4o-mini'),
            'OPENAI_URL': os.environ.get('OPENAI_URL'),
            'ACRCLOUD_TOKEN': os.environ.get('ACRCLOUD_TOKEN'),  # Add ACRCloud token
        }
        
        # Setup Spotify client if credentials are available
        if all([os.environ.get(key) for key in ['SPOTIFY_CLIENT_ID', 'SPOTIFY_CLIENT_SECRET']]):
            import spotipy
            from spotipy.oauth2 import SpotifyClientCredentials
            
            real_app.logger.info("Setting up Spotify client...")
            spotify_client_credentials = SpotifyClientCredentials(
                client_id=os.environ.get('SPOTIFY_CLIENT_ID'),
                client_secret=os.environ.get('SPOTIFY_CLIENT_SECRET')
            )
            real_app.config['sp'] = spotipy.Spotify(client_credentials_manager=spotify_client_credentials)
        
        # Setup Deezer client
        from musicround.deezer_client import DeezerClient
        real_app.config['deezer'] = DeezerClient()
        
        # Test MusicBrainz directly (doesn't need API keys)
        real_app.logger.info("Testing MusicBrainz API...")
        mb_data = get_musicbrainz_data(self.test_isrc, real_app.logger)
        self.assertIsNotNone(mb_data)
        if mb_data:
            real_app.logger.info(f"MusicBrainz data: {mb_data}")
            self.assertEqual(mb_data.get("title"), "Highway to Hell")
            self.assertIn("AC/DC", mb_data.get("artist_name", ""))
        
        # Test Spotify if client is available
        if real_app.config.get('sp'):
            real_app.logger.info("Testing Spotify API...")
            spotify_data = get_spotify_data(self.test_isrc, real_app)
            real_app.logger.info(f"Spotify data: {spotify_data}")
            self.assertIsNotNone(spotify_data)
            if spotify_data:
                self.assertEqual(spotify_data.get("title"), "Highway to Hell")
                self.assertIn("AC/DC", spotify_data.get("artist_name", ""))
        else:
            real_app.logger.warning("Skipping Spotify test: credentials not available")
        
        # Test Deezer API
        real_app.logger.info("Testing Deezer API...")
        deezer_data = get_deezer_data(self.test_isrc, real_app)
        real_app.logger.info(f"Deezer data: {deezer_data}")
        if deezer_data:
            self.assertIsNotNone(deezer_data)
            if "title" in deezer_data:
                self.assertEqual(deezer_data.get("title"), "Highway to Hell")
            if "artist_name" in deezer_data:
                self.assertIn("AC/DC", deezer_data.get("artist_name"))
        
        # Test Last.fm if API key is available
        if real_app.config.get('LASTFM_API_KEY'):
            real_app.logger.info("Testing Last.fm API...")
            lastfm_data = get_lastfm_data("AC/DC", "Highway to Hell", real_app)
            real_app.logger.info(f"Last.fm data: {lastfm_data}")
            self.assertIsNotNone(lastfm_data)
            if lastfm_data:
                self.assertIn("genre", lastfm_data)
        else:
            real_app.logger.warning("Skipping Last.fm test: API key not available")
        
        # Test OpenAI if API key is available
        if real_app.config.get('OPENAI_API_KEY'):
            real_app.logger.info("Testing OpenAI API...")
            openai_data = get_openai_data("AC/DC", "Highway to Hell", real_app)
            real_app.logger.info(f"OpenAI data: {openai_data}")
            self.assertIsNotNone(openai_data)
            if openai_data:
                self.assertIn("year", openai_data)
                # Convert to string for comparison if it's an integer
                expected_year = "1979"
                actual_year = str(openai_data.get("year")) if openai_data.get("year") is not None else None
                self.assertEqual(actual_year, expected_year)
        else:
            real_app.logger.warning("Skipping OpenAI test: API key not available")
        
        # Test ACRCloud if token is available
        if real_app.config.get('ACRCLOUD_TOKEN'):
            from musicround.helpers.metadata import get_acrcloud_data
            real_app.logger.info("Testing ACRCloud API...")
            acrcloud_data = get_acrcloud_data(self.test_isrc, real_app)
            real_app.logger.info(f"ACRCloud data: {acrcloud_data}")
            if acrcloud_data:
                self.assertIsNotNone(acrcloud_data)
                if "title" in acrcloud_data:
                    self.assertEqual(acrcloud_data.get("title"), "Highway to Hell")
                if "artist_name" in acrcloud_data:
                    self.assertIn("AC/DC", acrcloud_data.get("artist_name"))
                # Check if platform IDs were retrieved
                if "spotify_id" in acrcloud_data:
                    self.assertIsNotNone(acrcloud_data.get("spotify_id"))
                if "deezer_id" in acrcloud_data:
                    self.assertIsNotNone(acrcloud_data.get("deezer_id"))
        else:
            real_app.logger.warning("Skipping ACRCloud test: API token not available")
        
        # Full test with all APIs
        real_app.logger.info("Testing full metadata aggregation...")
        metadata = get_song_metadata_by_isrc(self.test_isrc, real_app)
        real_app.logger.info(f"Full metadata: {metadata}")
        
        self.assertIsNotNone(metadata)
        if metadata:
            self.assertEqual(metadata.get("title"), "Highway to Hell")
            self.assertIn("AC/DC", metadata.get("artist_name", ""))
            self.assertEqual(metadata.get("year"), "1979")
            self.assertIsNotNone(metadata.get("genre"))
            self.assertIn("musicbrainz", metadata.get("sources", []))
            
            # Check if we got data from other sources as expected
            if real_app.config.get('ACRCLOUD_TOKEN'):
                self.assertIn("acrcloud", metadata.get("sources", []))
            if real_app.config.get('sp'):
                self.assertIn("spotify", metadata.get("sources", []))
            if real_app.config.get('LASTFM_API_KEY'):
                self.assertIn("lastfm", metadata.get("sources", []))
            
            # Only check for OpenAI if we have both key and we've verified it works
            if real_app.config.get('OPENAI_API_KEY') and openai_data and ('genre' in openai_data or 'year' in openai_data):
                self.assertIn("openai", metadata.get("sources", []))


if __name__ == '__main__':
    unittest.main()
