"""Pytest configuration and fixtures for Quizzical Beats tests."""
import os
import sys
import tempfile
import pytest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _make_app():
    """
    Create a Flask application instance suitable for testing.

    The standard create_app() tries to access /data which may not be writable
    in CI environments.  We redirect that path to a temporary directory during
    app creation and then reconfigure SQLAlchemy to use an in-memory database
    for the actual test session.
    """
    # Set required environment variables before importing the app so that config
    # defaults are populated correctly.  Use setdefault so that values provided
    # by the test runner (e.g. SECRET_KEY=test pytest …) are not overridden.
    os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-testing-only')
    os.environ.setdefault('AUTOMATION_TOKEN', 'test-automation-token-for-testing')

    from musicround import create_app, db

    tmpdir = tempfile.mkdtemp()

    _orig_join = os.path.join
    _orig_exists = os.path.exists
    _orig_makedirs = os.makedirs

    def _join(*args):
        result = _orig_join(*args)
        if result == '/data/song_data.db':
            return os.path.join(tmpdir, 'test.db')
        return result

    def _exists(path):
        if path == '/data':
            return True
        return _orig_exists(path)

    def _makedirs(path, **kwargs):
        if path == '/data':
            return
        return _orig_makedirs(path, **kwargs)

    with patch('os.path.join', side_effect=_join), \
         patch('os.path.exists', side_effect=_exists), \
         patch('os.makedirs', side_effect=_makedirs):
        app = create_app()

    return app, db


@pytest.fixture
def app():
    """Create a test Flask application instance."""
    app, db = _make_app()

    test_config = {
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
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
