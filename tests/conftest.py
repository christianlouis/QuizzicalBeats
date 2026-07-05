"""Pytest configuration and fixtures for Quizzical Beats tests."""
import os
import sys
import tempfile
import pytest
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _make_app(database_uri, monkeypatch):
    """
    Create a Flask application instance suitable for testing.

    The standard create_app() falls back to /data when no database URI is
    configured. Tests should use an explicit temporary database so that app
    startup never touches production-like paths or developer environment DBs.
    """
    # Set required environment variables before importing the app so that config
    # defaults are populated correctly.  Use setdefault so that values provided
    # by the test runner (e.g. SECRET_KEY=test pytest …) are not overridden.
    os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-testing-only')
    os.environ.setdefault('AUTOMATION_TOKEN', 'test-automation-token-for-testing')

    monkeypatch.setenv('SQLALCHEMY_DATABASE_URI', database_uri)

    from musicround import create_app, db

    app = create_app()

    return app, db


@pytest.fixture
def app(monkeypatch):
    """Create a test Flask application instance."""
    tmpdir = tempfile.mkdtemp()
    database_uri = f"sqlite:///{os.path.join(tmpdir, 'test.db')}"
    app, db = _make_app(database_uri, monkeypatch)

    test_config = {
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': database_uri,
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'SECRET_KEY': 'test-secret-key-for-testing-only',
        'AUTOMATION_TOKEN': 'test-automation-token-for-testing',
        'WTF_CSRF_ENABLED': False,  # Disable CSRF for testing
    }
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
