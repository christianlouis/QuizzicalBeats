"""Pytest configuration and fixtures for Quizzical Beats tests."""
import os
import sys
import pytest
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture
def app():
    """Create a test Flask application instance."""
    from musicround import create_app, db
    
    # Create app in testing mode
    test_config = {
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'SECRET_KEY': 'test-secret-key-for-testing-only',
        'AUTOMATION_TOKEN': 'test-automation-token-for-testing',
        'WTF_CSRF_ENABLED': False,  # Disable CSRF for testing
    }
    
    app = create_app()
    app.config.update(test_config)
    
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Create a test client for the app."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Create a test CLI runner."""
    return app.test_cli_runner()


@pytest.fixture
def mock_app():
    """Create a mock Flask app for unit testing."""
    app = MagicMock()
    app.logger = MagicMock()
    app.config = {
        'SECRET_KEY': 'test-key',
        'AUTOMATION_TOKEN': 'test-token',
    }
    return app


@pytest.fixture
def mock_spotify_client():
    """Create a mock Spotify client."""
    client = MagicMock()
    client.search.return_value = {
        'tracks': {
            'items': []
        }
    }
    return client


@pytest.fixture
def sample_user_data():
    """Sample user data for testing."""
    return {
        'username': 'testuser',
        'email': 'test@example.com',
        'password': 'SecurePassword123!',
    }


@pytest.fixture
def sample_song_data():
    """Sample song data for testing."""
    return {
        'title': 'Highway to Hell',
        'artist_name': 'AC/DC',
        'year': '1979',
        'genre': 'Hard Rock',
        'isrc': 'AUAP07900028',
    }
